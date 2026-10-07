"""Persistent personal projects and preferences, alongside local accounts."""
import json
import secrets
import time

from . import auth


def connection():
    return auth.STORE.connect()


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
            description TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_images (
            project_id TEXT NOT NULL, filename TEXT NOT NULL,
            PRIMARY KEY (project_id, filename)
        );
        CREATE TABLE IF NOT EXISTS preferences (
            user_id INTEGER PRIMARY KEY, value TEXT NOT NULL
        );
    """)


def projects(user_id):
    with connection() as db:
        initialize(db)
        rows = db.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY created DESC", (user_id,)).fetchall()
        return [{"id": row["id"], "name": row["name"], "description": row["description"],
                 "created": row["created"], "images": [image[0] for image in db.execute(
                     "SELECT filename FROM project_images WHERE project_id = ? ORDER BY rowid DESC", (row["id"],))]}
                for row in rows]


def create(user_id, name, description):
    project_id = secrets.token_hex(12)
    with connection() as db:
        initialize(db)
        db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
                   (project_id, user_id, name, description, time.time()))
        db.commit()
    return project_id


def modify(user_id, project_id, action, filename=None, name=None, description=None):
    with connection() as db:
        initialize(db)
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT id FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone():
            return False
        if action == "delete":
            db.execute("DELETE FROM project_images WHERE project_id = ?", (project_id,))
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        elif action == "rename":
            db.execute("UPDATE projects SET name = ?, description = ? WHERE id = ?", (name, description, project_id))
        elif action == "add":
            db.execute("INSERT OR IGNORE INTO project_images VALUES (?, ?)", (project_id, filename))
        elif action == "remove":
            db.execute("DELETE FROM project_images WHERE project_id = ? AND filename = ?", (project_id, filename))
        db.commit()
    return True


def preferences(user_id, value=None):
    with connection() as db:
        initialize(db)
        if value is not None:
            db.execute("INSERT OR REPLACE INTO preferences VALUES (?, ?)", (user_id, json.dumps(value)))
            db.commit()
        row = db.execute("SELECT value FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else None
