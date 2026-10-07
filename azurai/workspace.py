"""Persistent personal projects and preferences, alongside local accounts."""
from psycopg.types.json import Jsonb
import secrets
import time

from . import auth


def connection():
    return auth.STORE.connect()




def projects(user_id):
    with connection() as db:
        rows = db.execute("SELECT * FROM projects WHERE user_id = %s ORDER BY created DESC", (user_id,)).fetchall()
        return [{"id": row["id"], "name": row["name"], "description": row["description"],
                 "created": row["created"], "images": [image[0] for image in db.execute(
                     "SELECT filename FROM project_images WHERE project_id = %s ORDER BY created DESC, filename", (row["id"],))]}
                for row in rows]


def create(user_id, name, description):
    project_id = secrets.token_hex(12)
    with connection() as db:
        db.execute("INSERT INTO projects VALUES (%s, %s, %s, %s, %s)",
                   (project_id, user_id, name, description, time.time()))
        db.commit()
    return project_id


def modify(user_id, project_id, action, filename=None, name=None, description=None):
    with connection() as db:
        if not db.execute("SELECT id FROM projects WHERE id=%s AND user_id=%s FOR UPDATE", (project_id, user_id)).fetchone():
            return False
        if action == "delete":
            db.execute("DELETE FROM project_images WHERE project_id = %s", (project_id,))
            db.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        elif action == "rename":
            db.execute("UPDATE projects SET name = %s, description = %s WHERE id = %s", (name, description, project_id))
        elif action == "add":
            db.execute("INSERT INTO project_images(project_id, filename) VALUES (%s, %s) ON CONFLICT DO NOTHING", (project_id, filename))
        elif action == "remove":
            db.execute("DELETE FROM project_images WHERE project_id = %s AND filename = %s", (project_id, filename))
        db.commit()
    return True


def preferences(user_id, value=None):
    with connection() as db:
        if value is not None:
            db.execute("INSERT INTO preferences VALUES (%s, %s) ON CONFLICT(user_id) DO UPDATE SET value=excluded.value", (user_id, Jsonb(value)))
            db.commit()
        row = db.execute("SELECT value FROM preferences WHERE user_id = %s", (user_id,)).fetchone()
    return row[0] if row else None


def director_draft(user_id, brief=None, expected_version=None):
    """One persisted working brief per account, with optimistic concurrency."""
    with connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"draft:{user_id}",))
        row = db.execute("SELECT version, value FROM director_drafts WHERE user_id = %s", (user_id,)).fetchone()
        version = row["version"] if row else 0
        if brief is not None:
            if expected_version != version:
                raise ValueError("Brief đã thay đổi ở cửa sổ khác. Tải lại brief trước khi lưu.")
            version += 1
            db.execute("INSERT INTO director_drafts VALUES (%s, %s, %s) ON CONFLICT(user_id) DO UPDATE SET version=excluded.version, value=excluded.value",
                       (user_id, version, Jsonb(brief)))
            db.commit()
            return {"version": version, "brief": brief}
    return {"version": version, "brief": row["value"] if row else None}
