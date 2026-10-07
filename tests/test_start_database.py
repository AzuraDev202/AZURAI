import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import start_database


class StartupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for patcher in [patch.object(start_database, "ROOT", self.root),
                        patch.object(start_database, "load_dotenv"),
                        patch.dict(os.environ, {"AZURAI_DATABASE_URL": "postgresql://azurai:test-password@127.0.0.1:5432/azurai"})]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_existing_database_is_checked_without_starting_processes(self):
        with patch.object(start_database.socket, "create_connection", return_value=MagicMock()), \
                patch.object(start_database.psycopg, "connect", return_value=MagicMock()) as connect, \
                patch.object(start_database.subprocess, "run") as run:
            start_database.main()
            self.assertIn("connect_timeout=3", connect.call_args.args[0])
            run.assert_not_called()

    def test_missing_database_reports_setup_instead_of_initializing(self):
        with patch.object(start_database.socket, "create_connection", side_effect=ConnectionRefusedError), \
                patch.object(start_database.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL is not running"):
                start_database.main()
            run.assert_not_called()

    def test_existing_uninitialized_data_is_not_overwritten(self):
        binary = self.root / ".cache/postgresql/pgsql/bin/pg_ctl.exe"
        binary.parent.mkdir(parents=True)
        binary.touch()
        existing = self.root / "data/postgresql/important.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("keep")
        with patch.object(start_database.socket, "create_connection", side_effect=ConnectionRefusedError), \
                patch.object(start_database.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                start_database.main()
            run.assert_not_called()
        self.assertEqual(existing.read_text(), "keep")

    def test_archive_cannot_extract_outside_install_directory(self):
        archive = self.root / ".cache/postgresql/binaries.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../../escape.txt", "no")
        with patch.object(start_database.socket, "create_connection", side_effect=ConnectionRefusedError), \
                self.assertRaisesRegex(RuntimeError, "Invalid archive path"):
            start_database.main()
        self.assertFalse((self.root / "escape.txt").exists())
