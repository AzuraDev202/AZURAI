"""Local accounts and revocable sessions stored in SQLite."""
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager

from .paths import ROOT

COOKIE = "azurai_session"
SESSION_SECONDS = 7 * 24 * 3600


class AccountStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    client TEXT NOT NULL, created REAL NOT NULL
                );
            """)
            yield connection

    @staticmethod
    def password_hash(password, salt):
        return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                              n=16384, r=8, p=1).hex()

    def register(self, username, password):
        salt = secrets.token_hex(16)
        hashed = self.password_hash(password, salt)
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users(username, salt, password_hash) VALUES (?, ?, ?)",
                    (username.lower(), salt, hashed))
                connection.commit()
            except sqlite3.IntegrityError:
                return None
            return {"id": cursor.lastrowid, "username": username.lower()}

    def authenticate(self, username, password):
        with self.connect() as connection:
            user = connection.execute("SELECT * FROM users WHERE username = ?", (username.lower(),)).fetchone()
        # Perform the same costly hash even for an unknown username.
        salt = user["salt"] if user else "00" * 16
        hashed = self.password_hash(password, salt)
        if user and hmac.compare_digest(user["password_hash"], hashed):
            return {"id": user["id"], "username": user["username"]}
        return None

    def allow_attempt(self, client):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM login_attempts WHERE created < ?", (time.time() - 600,))
            count = connection.execute("SELECT COUNT(*) FROM login_attempts WHERE client = ?", (client,)).fetchone()[0]
            allowed = count < 10
            if allowed:
                connection.execute("INSERT INTO login_attempts VALUES (?, ?)", (client, time.time()))
            connection.commit()
        return allowed

    def create_session(self, user):
        token = secrets.token_urlsafe(32)
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                               (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + SESSION_SECONDS))
            connection.commit()
        return token

    def session_user(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as connection:
            user = connection.execute("""
                SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE token_hash = ? AND expires > ?
            """, (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(user) if user else None

    def logout(self, token):
        if token:
            with self.connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?",
                                   (hashlib.sha256(token.encode()).hexdigest(),))
                connection.commit()


STORE = AccountStore(ROOT / "data" / "accounts.sqlite3")
