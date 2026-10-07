"""Copy a stopped AZURAI SQLite installation into an empty PostgreSQL database."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from azurai.auth import AccountStore

TABLES = {
    "users": ["id", "username", "salt", "password_hash"],
    "sessions": ["token_hash", "user_id", "expires"],
    "login_attempts": ["client", "created"],
    "projects": ["id", "user_id", "name", "description", "created"],
    "project_images": ["project_id", "filename", "created"],
    "preferences": ["user_id", "value"],
    "director_drafts": ["user_id", "version", "value"],
    "legacy_imports": ["path", "applied"],
    "creative_profiles": ["user_id", "value"],
    "director_runs": ["id", "user_id", "phase", "request", "response", "created"],
    "generation_jobs": ["id", "user_id", "operation", "parameters", "creative", "state", "progress", "message", "filename", "created", "updated"],
    "images": ["filename", "user_id", "png", "metadata", "created"],
    "image_feedback": ["user_id", "filename", "rating", "note", "updated"],
}
JSON_COLUMNS = {"value", "request", "response", "parameters", "creative", "metadata"}


def migrate(source_path, store=None):
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError("Không tìm thấy SQLite nguồn.")
    store = store or AccountStore()
    counts = {}
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source, store.connect() as target:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        target.execute("SET LOCAL lock_timeout='10s'")
        target.execute("SELECT pg_advisory_xact_lock(41003, 0)")
        target.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(sql.SQL(", ").join(sql.Identifier(name) for name in TABLES)))
        for table in TABLES:
            if target.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM {})").format(sql.Identifier(table))).fetchone()[0]:
                raise ValueError("PostgreSQL đích phải trống. Migration không ghi đè dữ liệu có sẵn.")
        available = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "users" not in available:
            raise ValueError("SQLite nguồn không phải database AZURAI.")
        for table, columns in TABLES.items():
            if table not in available:
                counts[table] = 0
                continue
            source_columns = {row[1] for row in source.execute(f'PRAGMA table_info("{table}")')}
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns))
            total = 0
            for row in source.execute(f'SELECT rowid AS __source_rowid, * FROM "{table}"'):
                values = []
                for column in columns:
                    if column == "created" and table == "project_images" and column not in source_columns:
                        value = float(row["__source_rowid"])
                    else:
                        value = row[column]
                    if column in JSON_COLUMNS and value is not None:
                        value = Jsonb(json.loads(value))
                    values.append(value)
                target.execute(statement, values)
                if table == "images":
                    stored = target.execute("SELECT png FROM images WHERE filename=%s", (row["filename"],)).fetchone()[0]
                    if bytes(stored) != bytes(row["png"]):
                        raise ValueError("Dữ liệu PNG không khớp sau migration.")
                total += 1
            actual = target.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            if actual != total:
                raise ValueError("Số bản ghi không khớp sau migration.")
            counts[table] = total
        for table in ("users", "director_runs"):
            target.execute(sql.SQL("SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}").format(sql.Identifier(table)), (table,))
        target.execute("INSERT INTO schema_migrations VALUES (4, EXTRACT(EPOCH FROM clock_timestamp())) ON CONFLICT DO NOTHING")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source), ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, sqlite3.Error, psycopg.Error):
        print("Migration thất bại; dữ liệu đích đã rollback. Kiểm tra cấu hình, database đích trống và SQLite nguồn hợp lệ.", file=sys.stderr)
        raise SystemExit(1)
