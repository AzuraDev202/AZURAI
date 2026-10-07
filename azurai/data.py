"""Unified local application data in the existing SQLite account database."""
import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from . import auth


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = True
    learn_from_feedback: bool = True
    purpose: str = Field(default="", max_length=500)
    style: str = Field(default="", max_length=300)
    palette: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=300)
    avoid: str = Field(default="", max_length=500)


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS legacy_imports (path TEXT PRIMARY KEY, applied REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS creative_profiles (user_id INTEGER PRIMARY KEY REFERENCES users(id), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS director_runs (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            phase TEXT NOT NULL, request TEXT NOT NULL, response TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS generation_jobs (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            operation TEXT NOT NULL, parameters TEXT NOT NULL, creative TEXT,
            state TEXT NOT NULL, progress REAL NOT NULL, message TEXT NOT NULL,
            filename TEXT, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS images (
            filename TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
            png BLOB NOT NULL, metadata TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS image_feedback (
            user_id INTEGER NOT NULL REFERENCES users(id), filename TEXT NOT NULL REFERENCES images(filename),
            rating INTEGER NOT NULL CHECK(rating IN (-1, 0, 1)), note TEXT NOT NULL, updated REAL NOT NULL,
            PRIMARY KEY(user_id, filename)
        );
        CREATE INDEX IF NOT EXISTS jobs_by_user ON generation_jobs(user_id, created DESC);
        CREATE INDEX IF NOT EXISTS images_by_user ON images(user_id, created DESC);
        CREATE INDEX IF NOT EXISTS director_runs_by_user ON director_runs(user_id, created DESC);
        INSERT OR IGNORE INTO schema_migrations VALUES (2, unixepoch());
    """)


def connection():
    return auth.STORE.connect()


def profile(user_id, value=None):
    with connection() as db:
        initialize(db)
        if value is not None:
            db.execute("INSERT INTO creative_profiles VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET value=excluded.value", (user_id, json.dumps(value)))
            db.commit()
        row = db.execute("SELECT value FROM creative_profiles WHERE user_id=?", (user_id,)).fetchone()
    return Profile.model_validate_json(row[0]).model_dump() if row else Profile().model_dump()


def personal_context(user_id):
    preferences = profile(user_id)
    if not preferences["enabled"]:
        return {}
    examples = []
    if preferences["learn_from_feedback"]:
        with connection() as db:
            initialize(db)
            rows = db.execute("""SELECT i.metadata, f.rating, f.note FROM image_feedback f
                JOIN images i ON i.filename=f.filename
                WHERE f.user_id=? AND f.rating!=0 AND (i.user_id=? OR i.user_id IS NULL)
                ORDER BY f.updated DESC LIMIT 8""", (user_id, user_id)).fetchall()
            for row in rows:
                metadata = json.loads(row["metadata"])
                creative = metadata.get("creative")
                brief = creative.get("brief", {}) if isinstance(creative, dict) else {}
                if not isinstance(brief, dict):
                    continue
                examples.append({"rating": row["rating"], "note": row["note"],
                                 "visual_preferences": {key: brief[key] for key in
                                  ("style", "palette", "lighting", "shot", "mood") if key in brief}})
    return {"profile": preferences, "feedback_examples": examples}


def record_director(user_id, phase, request, response):
    with connection() as db:
        initialize(db)
        db.execute("INSERT INTO director_runs(user_id, phase, request, response, created) VALUES (?, ?, ?, ?, ?)",
                   (user_id, phase, json.dumps(request, ensure_ascii=False), json.dumps(response, ensure_ascii=False), time.time()))
        db.commit()


def create_job(job_id, user_id, operation, parameters, creative):
    now = time.time()
    with connection() as db:
        initialize(db)
        db.execute("INSERT INTO generation_jobs VALUES (?, ?, ?, ?, ?, 'running', 0, ?, NULL, ?, ?)",
                   (job_id, user_id, operation, json.dumps(parameters), json.dumps(creative) if creative else None,
                    "Đang chuẩn bị mô hình…", now, now))
        db.commit()


def update_job(job_id, state, message, progress=0, filename=None):
    with connection() as db:
        initialize(db)
        db.execute("UPDATE generation_jobs SET state=?, message=?, progress=?, filename=COALESCE(?, filename), updated=? WHERE id=?",
                   (state, message, progress, filename, time.time(), job_id))
        db.commit()


def job(job_id, user_id):
    with connection() as db:
        initialize(db)
        row = db.execute("SELECT id, operation, state, progress, message, filename, created, parameters, creative FROM generation_jobs WHERE id=? AND user_id=?",
                         (job_id, user_id)).fetchone()
    if not row:
        return None
    result = dict(row)
    parameters = json.loads(result.pop("parameters"))
    result["prompt"] = parameters.get("prompt", "")
    result["negative"] = parameters.get("negative", "")
    result["creative"] = json.loads(result["creative"]) if result["creative"] else None
    return result


def history(user_id):
    with connection() as db:
        initialize(db)
        rows = db.execute("SELECT id, operation, state, progress, message, filename, created FROM generation_jobs WHERE user_id=? ORDER BY created DESC LIMIT 100", (user_id,)).fetchall()
    return [dict(row) for row in rows]


def recover_jobs():
    with connection() as db:
        initialize(db)
        db.execute("UPDATE generation_jobs SET state='error', message=?, updated=? WHERE state='running'",
                   ("Máy chủ đã khởi động lại; hãy tạo ảnh lại.", time.time()))
        db.commit()


def store_image(filename, png, metadata, user_id=None, created=None):
    with connection() as db:
        initialize(db)
        db.execute("INSERT OR IGNORE INTO images VALUES (?, ?, ?, ?, ?)",
                   (filename, user_id, png, json.dumps(metadata, ensure_ascii=False), created or time.time()))
        db.commit()


def import_legacy(outputs):
    """Idempotent import. Legacy images stay shared; never assign them to a new user."""
    with connection() as db:
        initialize(db)
        source = str(Path(outputs).resolve())
        if db.execute("SELECT path FROM legacy_imports WHERE path=?", (source,)).fetchone():
            return
        known = {row[0] for row in db.execute("SELECT filename FROM images")}
        owners = {row["filename"]: row["user_id"] for row in db.execute("SELECT filename, user_id FROM generation_jobs WHERE filename IS NOT NULL")}
    for path in Path(outputs).glob("*.png"):
        if path.name in known or path.is_symlink():
            continue
        try:
            sidecar = path.with_suffix(".json")
            metadata = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() and sidecar.stat().st_size < 1024**2 else {}
            if not isinstance(metadata, dict):
                metadata = {}
        except (OSError, ValueError):
            metadata = {}
        store_image(path.name, path.read_bytes(), metadata, user_id=owners.get(path.name), created=path.stat().st_mtime)
    with connection() as db:
        db.execute("INSERT OR IGNORE INTO legacy_imports VALUES (?, ?)", (source, time.time()))
        db.commit()


def image(filename, user_id):
    if Path(filename).name != filename or not filename.lower().endswith(".png"):
        return None
    with connection() as db:
        initialize(db)
        row = db.execute("SELECT png, metadata, user_id FROM images WHERE filename=? AND (user_id=? OR user_id IS NULL)", (filename, user_id)).fetchone()
    return dict(row) if row else None


def library(user_id):
    with connection() as db:
        initialize(db)
        rows = db.execute("""SELECT i.filename, i.metadata, i.created, i.user_id, COALESCE(f.rating, 0) AS rating
            FROM images i LEFT JOIN image_feedback f ON f.filename=i.filename AND f.user_id=?
            WHERE i.user_id=? OR i.user_id IS NULL ORDER BY i.created DESC""", (user_id, user_id)).fetchall()
    result = []
    for row in rows:
        meta = json.loads(row["metadata"])
        result.append({"filename": row["filename"], "created": row["created"], "prompt": str(meta.get("prompt", "")),
                       "width": meta.get("width"), "height": meta.get("height"), "creative": meta.get("creative"),
                       "rating": row["rating"], "legacy_shared": row["user_id"] is None,
                       "parameters": {key: meta[key] for key in ("negative", "seed", "steps", "guidance", "width", "height") if key in meta}})
    return result


def feedback(user_id, filename, rating, note):
    if not image(filename, user_id):
        return False
    with connection() as db:
        initialize(db)
        db.execute("INSERT INTO image_feedback VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, filename) DO UPDATE SET rating=excluded.rating, note=excluded.note, updated=excluded.updated",
                   (user_id, filename, rating, note, time.time()))
        db.commit()
    return True


def clear_feedback(user_id):
    with connection() as db:
        initialize(db)
        db.execute("DELETE FROM image_feedback WHERE user_id=?", (user_id,))
        db.commit()
