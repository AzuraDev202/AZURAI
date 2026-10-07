"""Consistent PostgreSQL custom-format backup using pg_dump."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from azurai import auth


def backup(destination, store=None):
    destination = Path(destination).resolve()
    store = store or auth.STORE
    if destination.exists():
        raise FileExistsError("Chọn tên backup mới để tránh ghi đè.")
    executable = shutil.which("pg_dump")
    if not executable:
        raise RuntimeError("Cần cài PostgreSQL client và thêm pg_dump vào PATH.")
    # Supply credentials through the child environment rather than command-line arguments.
    settings = conninfo_to_dict(store.url())
    env = os.environ.copy()
    for key, value in settings.items():
        env["PGDATABASE" if key == "dbname" else "PG" + key.upper()] = str(value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("xb"):
        pass
    try:
        result = subprocess.run([executable, "--format=custom", "--no-owner", "--no-acl", "--file", str(temporary)],
                                env=env, capture_output=True)
        if result.returncode:
            raise RuntimeError("pg_dump thất bại. Kiểm tra kết nối, quyền truy cập và phiên bản PostgreSQL client.")
        # Keep no-overwrite semantics even if another process created the destination while dumping.
        with temporary.open("rb") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    try:
        print(backup(parser.parse_args().destination))
    except (OSError, RuntimeError):
        print("Backup thất bại. Kiểm tra PostgreSQL, pg_dump trong PATH và tên đích chưa tồn tại.", file=sys.stderr)
        raise SystemExit(1)
