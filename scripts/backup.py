"""Consistent SQLite backup, including committed WAL data and PNG assets."""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from azurai import auth


def backup(destination):
    destination = Path(destination).resolve()
    if not auth.STORE.path.is_file():
        raise FileNotFoundError("Chưa có database AZURAI.")
    if destination.exists():
        raise FileExistsError("Chọn tên backup mới để tránh ghi đè.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with auth.STORE.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup không vượt qua integrity check.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(backup(parser.parse_args().destination))
