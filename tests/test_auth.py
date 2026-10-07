import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from azurai import api, auth
from fixtures import postgres_store


class AuthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = postgres_store(self)
        patcher = patch.object(auth, "STORE", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, base_url="http://127.0.0.1")
        self.credentials = {"username": "alice", "password": "secret-password"}

    def register(self):
        response = self.client.post("/api/auth/register", json=self.credentials)
        self.assertEqual(response.status_code, 201)
        return response

    def test_guests_can_view_home_but_cannot_use_studio_or_images(self):
        self.assertIn('id="homeView"', self.client.get("/").text)
        self.assertIsNone(self.client.get("/api/auth/session").json()["user"])
        for route in ["/api/options", "/api/device", "/api/library", "/api/jobs/fake", "/api/images/fake", "/api/library/fake.png"]:
            self.assertEqual(self.client.get(route).status_code, 401)
        with patch.object(api.SERVICE, "generate") as generate:
            self.assertEqual(self.client.post("/api/generate", json={"prompt": "cat"}).status_code, 401)
            generate.assert_not_called()

    def test_register_login_logout_revokes_old_token(self):
        response = self.register()
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        token = self.client.cookies.get(auth.COOKIE)
        self.assertEqual(self.client.get("/api/auth/session").json()["user"]["username"], "alice")
        self.assertEqual(self.client.get("/api/options").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertIsNone(self.store.session_user(token))
        self.assertEqual(self.client.get("/api/options", headers={"Cookie": f"{auth.COOKIE}={token}"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json=self.credentials).status_code, 200)
        self.assertNotEqual(self.client.cookies.get(auth.COOKIE), token)

    def test_passwords_and_tokens_are_hashed_and_accounts_persist(self):
        self.register()
        token = self.client.cookies.get(auth.COOKIE)
        with self.store.connect() as connection:
            user = connection.execute("SELECT * FROM users").fetchone()
            session = connection.execute("SELECT * FROM sessions").fetchone()
        self.assertNotEqual(user["password_hash"], self.credentials["password"])
        self.assertEqual(session["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        reopened = auth.AccountStore(self.store.dsn)
        self.assertEqual(reopened.authenticate("ALICE", self.credentials["password"])["username"], "alice")
        self.assertEqual(reopened.session_user(token)["username"], "alice")

    def test_duplicate_invalid_and_incorrect_credentials(self):
        self.register()
        self.assertEqual(self.client.post("/api/auth/register", json=self.credentials).status_code, 409)
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "bad name", "password": "123"}).status_code, 422)
        for name in ["alice", "unknown"]:
            response = self.client.post("/api/auth/login", json={"username": name, "password": "wrong-password"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "Tên đăng nhập hoặc mật khẩu không đúng.")

    def test_expired_sessions_and_cross_origin_auth_are_rejected(self):
        self.register()
        with self.store.connect() as connection:
            connection.execute("UPDATE sessions SET expires = %s", (time.time() - 1,))
            connection.commit()
        self.assertEqual(self.client.get("/api/library").status_code, 401)
        for route in ["login", "register", "logout"]:
            response = self.client.post(f"/api/auth/{route}", json=self.credentials, headers={"Origin": "https://example.com"})
            self.assertEqual(response.status_code, 403)

    def test_repeated_login_attempts_are_limited(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/auth/login", json=self.credentials).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json=self.credentials).status_code, 429)


if __name__ == "__main__":
    unittest.main()
