"""Local accounts and revocable sessions stored in PostgreSQL."""
import hashlib
import hmac
import secrets
import psycopg
import time


from .database import Database

COOKIE = "azurai_session"
SESSION_SECONDS = 7 * 24 * 3600


class AccountStore(Database):
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
                    "INSERT INTO users(username, salt, password_hash) VALUES (%s, %s, %s) RETURNING id",
                    (username.lower(), salt, hashed)).fetchone()
                connection.commit()
            except psycopg.errors.UniqueViolation:
                connection.rollback()
                return None
            return {"id": cursor["id"], "username": username.lower()}

    def authenticate(self, username, password):
        with self.connect() as connection:
            user = connection.execute("SELECT * FROM users WHERE username = %s", (username.lower(),)).fetchone()
        # Perform the same costly hash even for an unknown username.
        salt = user["salt"] if user else "00" * 16
        hashed = self.password_hash(password, salt)
        if user and hmac.compare_digest(user["password_hash"], hashed):
            return {"id": user["id"], "username": user["username"]}
        return None

    def allow_attempt(self, client):
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("login:" + client,))
            connection.execute("DELETE FROM login_attempts WHERE created < %s", (time.time() - 600,))
            count = connection.execute("SELECT COUNT(*) FROM login_attempts WHERE client = %s", (client,)).fetchone()[0]
            allowed = count < 10
            if allowed:
                connection.execute("INSERT INTO login_attempts VALUES (%s, %s)", (client, time.time()))
            connection.commit()
        return allowed

    def create_session(self, user):
        token = secrets.token_urlsafe(32)
        with self.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires <= %s", (time.time(),))
            connection.execute("INSERT INTO sessions VALUES (%s, %s, %s)",
                               (hashlib.sha256(token.encode()).hexdigest(), user["id"], time.time() + SESSION_SECONDS))
            connection.commit()
        return token

    def session_user(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as connection:
            user = connection.execute("""
                SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE token_hash = %s AND expires > %s
            """, (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(user) if user else None

    def logout(self, token):
        if token:
            with self.connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = %s",
                                   (hashlib.sha256(token.encode()).hexdigest(),))
                connection.commit()


STORE = AccountStore()
