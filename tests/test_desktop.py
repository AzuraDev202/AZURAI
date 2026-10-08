"""Desktop lifecycle, persistent storage and configuration behavior."""
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from azurai.desktop import LocalServer, initialize_data, save_settings


class DesktopTests(unittest.TestCase):
    def test_data_initialization_preserves_user_config_and_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            resources = Path(__file__).resolve().parents[1]
            initialize_data(root, resources)
            (root / 'config/models.json').write_text('custom', encoding='utf-8')
            (root / 'outputs/user.png').write_bytes(b'image')
            initialize_data(root, resources)
            self.assertEqual((root / 'config/models.json').read_text(), 'custom')
            self.assertEqual((root / 'outputs/user.png').read_bytes(), b'image')
            self.assertTrue((root / 'config/prompts.json').is_file())

    def test_dotenv_roundtrip_special_characters_and_no_partial_file(self):
        from dotenv import dotenv_values
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            url = 'postgresql://user:p%23ass%22word@localhost:5432/azurai'
            save_settings(root, url, 'qwen2.5:7b')
            values = dotenv_values(root / '.env')
            self.assertEqual(values['AZURAI_DATABASE_URL'], url)
            self.assertEqual(values['AZURAI_DIRECTOR_MODEL'], 'qwen2.5:7b')
            self.assertFalse((root / '.env.part').exists())
            with self.assertRaises(ValueError):
                save_settings(root, 'sqlite://test', 'model')
            self.assertEqual(dotenv_values(root / '.env')['AZURAI_DATABASE_URL'], url)

    def test_frozen_resources_are_separate_from_writable_storage(self):
        import azurai.paths as paths
        try:
            with tempfile.TemporaryDirectory() as temporary:
                with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', str(Path(temporary)/'bundle'), create=True), patch.dict(os.environ, {'AZURAI_DATA_DIR':str(Path(temporary)/'user')}):
                    importlib.reload(paths)
                    self.assertEqual(paths.ROOT, Path(temporary)/'user')
                    self.assertEqual(paths.FRONTEND_DIR, Path(temporary)/'bundle/frontend')
                    self.assertEqual(paths.CONFIG_DIR, Path(temporary)/'user/config')
        finally:
            importlib.reload(paths)

    def test_backend_binds_loopback_serves_and_stops(self):
        from fastapi import FastAPI
        import httpx
        app = FastAPI()
        @app.get('/')
        def root():
            return {'desktop':True}
        server = LocalServer(app)
        try:
            url = server.start(timeout=10)
            self.assertEqual(server.socket.getsockname()[0], '127.0.0.1')
            self.assertEqual(httpx.get(url, trust_env=False).json(), {'desktop':True})
        finally:
            server.close()
        self.assertFalse(server.thread.is_alive())

    def test_failed_backend_start_does_not_open_window_or_leave_thread(self):
        from fastapi import FastAPI
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def lifespan(app):
            raise RuntimeError('unavailable DB')
            yield
        server = LocalServer(FastAPI(lifespan=lifespan))
        with self.assertRaises(RuntimeError):
            server.start(timeout=5)
        self.assertFalse(server.thread.is_alive())
