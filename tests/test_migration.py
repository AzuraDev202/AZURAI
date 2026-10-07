import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from azurai import auth, workspace
from fixtures import postgres_store
from scripts.migrate_sqlite import migrate
from scripts.backup import backup


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.store = postgres_store(self)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "old.sqlite3"
        salt = "12" * 16
        password_hash = auth.AccountStore.password_hash("test-password", salt)
        with sqlite3.connect(self.source) as db:
            db.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, salt TEXT, password_hash TEXT);
                CREATE TABLE projects(id TEXT, user_id INTEGER, name TEXT, description TEXT, created REAL);
                CREATE TABLE project_images(project_id TEXT, filename TEXT);
                CREATE TABLE preferences(user_id INTEGER, value TEXT);
                CREATE TABLE images(filename TEXT, user_id INTEGER, png BLOB, metadata TEXT, created REAL);
                CREATE TABLE sessions(token_hash TEXT, user_id INTEGER, expires REAL);
                CREATE TABLE director_drafts(user_id INTEGER, version INTEGER, value TEXT);
                CREATE TABLE creative_profiles(user_id INTEGER, value TEXT);
                CREATE TABLE director_runs(id INTEGER PRIMARY KEY, user_id INTEGER, phase TEXT, request TEXT, response TEXT, created REAL);
                CREATE TABLE generation_jobs(id TEXT, user_id INTEGER, operation TEXT, parameters TEXT, creative TEXT, state TEXT, progress REAL, message TEXT, filename TEXT, created REAL, updated REAL);
                CREATE TABLE image_feedback(user_id INTEGER, filename TEXT, rating INTEGER, note TEXT, updated REAL);
            ''')
            db.execute("INSERT INTO users VALUES(42, 'alice', ?, ?)", (salt, password_hash))
            db.execute("INSERT INTO sessions VALUES('hashed-session',42,9999999999)")
            db.execute("INSERT INTO director_drafts VALUES(42,7,'{\"idea\":\"cat\"}')")
            db.execute("INSERT INTO creative_profiles VALUES(42,'{\"style\":\"watercolor\"}')")
            db.execute("INSERT INTO director_runs VALUES(55,42,'concepts','{}','{}',1)")
            db.execute("INSERT INTO generation_jobs VALUES('job',42,'generate','{\"seed\":123}',NULL,'done',1,'saved','a.png',1,1)")
            db.execute("INSERT INTO projects VALUES('p',42,'Old project','kept',1)")
            db.execute("INSERT INTO project_images VALUES('p','a.png')")
            db.execute("INSERT INTO preferences VALUES(42, '{\"seed\":123}')")
            db.execute("INSERT INTO images VALUES('a.png',42,?, '{\"prompt\":\"xin chào\"}',1)", (b'\x89PNG\x00\xff',))
            db.execute("INSERT INTO image_feedback VALUES(42,'a.png',1,'warm',1)")

    def test_migration_preserves_ids_hashes_json_png_and_source(self):
        original = hashlib.sha256(self.source.read_bytes()).digest()
        counts = migrate(self.source, self.store)
        self.assertEqual(counts['users'], 1)
        self.assertEqual(self.store.authenticate('alice', 'test-password')['id'], 42)
        self.assertGreater(self.store.register('bob', 'test-password')['id'], 42)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM images').fetchone()
            self.assertEqual(row['png'], b'\x89PNG\x00\xff')
            self.assertEqual(row['user_id'], 42)
            self.assertEqual(row['metadata'], {'prompt': 'xin chào'})
            self.assertEqual(db.execute('SELECT created FROM project_images').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT value FROM preferences').fetchone()[0], {'seed': 123})
            self.assertEqual(db.execute('SELECT version, value FROM director_drafts').fetchone(), {'version': 7, 'value': {'idea': 'cat'}})
            self.assertEqual(db.execute('SELECT value FROM creative_profiles').fetchone()[0], {'style': 'watercolor'})
            self.assertEqual(db.execute('SELECT parameters, creative FROM generation_jobs').fetchone(), {'parameters': {'seed': 123}, 'creative': None})
            self.assertEqual(db.execute('SELECT token_hash FROM sessions').fetchone()[0], 'hashed-session')
            new_id = db.execute("INSERT INTO director_runs(user_id,phase,request,response,created) VALUES(42,'review','{}','{}',2) RETURNING id").fetchone()[0]
            self.assertGreater(new_id, 55)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), original)
        with self.assertRaises(ValueError):
            migrate(self.source, self.store)

    def test_invalid_json_rolls_back_all_rows(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE preferences SET value='broken'")
        with self.assertRaises(ValueError):
            migrate(self.source, self.store)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 0)

    def test_simultaneous_draft_updates_have_one_winner(self):
        user = self.store.register('alice', 'test-password')['id']
        with patch.object(auth, 'STORE', self.store):
            with ThreadPoolExecutor(max_workers=2) as pool:
                def save(_):
                    try:
                        return workspace.director_draft(user, {'idea': 'cat'}, 0)
                    except ValueError:
                        return None
                outcomes = list(pool.map(save, range(2)))
            self.assertEqual(sum(result is not None for result in outcomes), 1)
            self.assertEqual(workspace.director_draft(user)['version'], 1)

    def test_backup_custom_archive_preserves_rows(self):
        if not shutil.which('pg_dump') or not shutil.which('pg_restore'):
            self.skipTest('PostgreSQL client tools required')
        import os
        import subprocess
        from psycopg.conninfo import conninfo_to_dict
        from psycopg import sql
        migrate(self.source, self.store)
        destination = Path(self.directory.name) / 'backup.dump'
        backup(destination, self.store)
        self.assertEqual(destination.read_bytes()[:5], b'PGDMP')
        restored_sql = subprocess.run(['pg_restore', '--file=-', str(destination)], capture_output=True, check=True).stdout
        self.assertIn(b'Old project', restored_sql)
        self.assertIn(b'\\x89504e4700ff', restored_sql)
        with self.assertRaises(FileExistsError):
            backup(destination, self.store)
        settings = conninfo_to_dict(self.store.url())
        env = os.environ.copy()
        for key, value in settings.items():
            env['PGDATABASE' if key == 'dbname' else 'PG' + key.upper()] = value
        with self.store.connect() as db:
            schema = db.execute('SELECT current_schema()').fetchone()[0]
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        result = subprocess.run(['pg_restore', '--no-owner', '--no-acl', '--exit-on-error',
                        '--schema', schema, '--dbname', settings['dbname'], str(destination)],
                       env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.store.authenticate('alice', 'test-password')['id'], 42)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT png FROM images').fetchone()[0], b'\x89PNG\x00\xff')
            self.assertEqual(db.execute('SELECT state FROM generation_jobs').fetchone()[0], 'done')


class ConfigurationTests(unittest.TestCase):
    def test_sqlite_is_not_a_runtime_fallback(self):
        with self.assertRaises(RuntimeError):
            auth.AccountStore('sqlite:///old.db').url()


if __name__ == '__main__':
    unittest.main()
