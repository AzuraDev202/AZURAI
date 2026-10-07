import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from azurai import auth, data, workspace
from fixtures import brief
from scripts.backup import backup


class DataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "accounts.sqlite3"
        self.store = auth.AccountStore(self.path)
        self.store_patch = patch.object(auth, "STORE", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.alice = self.store.register("alice", "test-password")["id"]
        self.bob = self.store.register("bob", "test-password")["id"]

    def test_migration_preserves_accounts_projects_and_preferences(self):
        workspace.create(self.alice, "Existing project", "kept")
        workspace.preferences(self.alice, {"seed": 42})
        data.profile(self.alice)
        self.assertIsNotNone(self.store.authenticate("alice", "test-password"))
        self.assertEqual(workspace.projects(self.alice)[0]["name"], "Existing project")
        self.assertEqual(workspace.preferences(self.alice)["seed"], 42)
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("SELECT version FROM schema_migrations").fetchone()[0], 2)

    def test_profiles_feedback_and_memory_are_account_scoped_and_optional(self):
        profile = data.Profile(style="cinematic", avoid="neon").model_dump()
        data.profile(self.alice, profile)
        self.assertEqual(data.profile(self.bob)["style"], "")
        data.store_image("a.png", b"png", {"creative": {"brief": brief().model_dump()}}, self.alice)
        self.assertFalse(data.feedback(self.bob, "a.png", 1, "stolen"))
        self.assertTrue(data.feedback(self.alice, "a.png", 1, "warm light"))
        personal = data.personal_context(self.alice)
        self.assertEqual(personal["feedback_examples"][0]["note"], "warm light")
        self.assertEqual(data.personal_context(self.bob)["feedback_examples"], [])
        data.profile(self.alice, {**profile, "learn_from_feedback": False})
        self.assertEqual(data.personal_context(self.alice)["feedback_examples"], [])
        data.profile(self.alice, {**profile, "enabled": False})
        self.assertEqual(data.personal_context(self.alice), {})
        data.clear_feedback(self.alice)
        self.assertEqual(data.library(self.alice)[0]["rating"], 0)

    def test_png_and_metadata_survive_file_removal_and_store_reopen(self):
        metadata = {"prompt": "cat", "creative": {"brief": brief().model_dump()}}
        data.store_image("a.png", b"png-bytes", metadata, self.alice)
        self.assertEqual(data.image("a.png", self.alice)["png"], b"png-bytes")
        self.assertIsNone(data.image("a.png", self.bob))
        self.assertEqual(json.loads(data.image("a.png", self.alice)["metadata"]), metadata)
        self.assertIsNone(data.image("../a.png", self.alice))

    def test_legacy_import_is_idempotent_and_shared_without_assigning_owner(self):
        outputs = Path(self.directory.name) / "outputs"
        outputs.mkdir()
        (outputs / "old.png").write_bytes(b"old-png")
        (outputs / "old.json").write_text('{"prompt":"legacy"}')
        data.import_legacy(outputs)
        data.import_legacy(outputs)
        (outputs / "old.png").unlink()
        self.assertEqual(len(data.library(self.alice)), 1)
        self.assertEqual(data.library(self.bob)[0]["prompt"], "legacy")
        self.assertTrue(data.library(self.alice)[0]["legacy_shared"])

    def test_persistent_job_ownership_recovery_and_consistent_backup(self):
        data.create_job("job", self.alice, "generate", {"seed": 42}, {"brief": brief().model_dump()})
        self.assertIsNone(data.job("job", self.bob))
        data.recover_jobs()
        self.assertEqual(data.job("job", self.alice)["state"], "error")
        data.store_image("a.png", b"png", {}, self.alice)
        destination = Path(self.directory.name) / "backup.sqlite3"
        backup(destination)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute("SELECT png FROM images").fetchone()[0], b"png")
            self.assertEqual(db.execute("SELECT state FROM generation_jobs").fetchone()[0], "error")
        with self.assertRaises(FileExistsError):
            backup(destination)


if __name__ == "__main__":
    unittest.main()
