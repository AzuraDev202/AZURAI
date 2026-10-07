"""Check PostgreSQL and start the project's portable instance when needed."""
import os
import socket
import subprocess
import tempfile
import zipfile
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env")
    dsn = os.environ.get("AZURAI_DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("Set AZURAI_DATABASE_URL in .env first.")
    settings = conninfo_to_dict(dsn)
    host = settings.get("host", "localhost")
    port = int(settings.get("port", 5432))
    try:
        with socket.create_connection((host, port), timeout=3):
            available = True
    except OSError:
        available = False
    if not available:
        if host not in ("localhost", "127.0.0.1"):
            raise RuntimeError("Remote PostgreSQL is unreachable. Check its service and network.")
        install = ROOT / ".cache" / "postgresql"
        binaries = install / "pgsql" / "bin"
        archive = install / "binaries.zip"
        if not (binaries / "pg_ctl.exe").is_file() and archive.is_file():
            if not zipfile.is_zipfile(archive):
                raise RuntimeError("PostgreSQL ZIP is incomplete or damaged. Finish downloading it before running AZURAI.")
            print("Extracting portable PostgreSQL...", flush=True)
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.infolist():
                    target = (install / entry.filename).resolve()
                    if not target.is_relative_to(install.resolve()):
                        raise RuntimeError("Invalid archive path.")
                    if entry.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                        bundle.extract(entry, install)
        if not (binaries / "pg_ctl.exe").is_file():
            raise RuntimeError("PostgreSQL is not running. Start Docker with docker compose up -d --wait, "
                               "or place the EDB PostgreSQL binaries ZIP in .cache/postgresql/binaries.zip.")
        cluster = ROOT / "data" / "postgresql"
        username = settings.get("user", "azurai")
        password = settings.get("password", "")

        def run(command):
            # A PostgreSQL child can inherit pipes on Windows. A file avoids
            # waiting for the long-lived server to close those pipes.
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                        stderr=subprocess.STDOUT, check=False)
                if result.returncode:
                    output.seek(0)
                    message = output.read().strip()
                    if password:
                        message = message.replace(password, "[redacted]")
                    raise RuntimeError(message or "PostgreSQL command failed.")

        if not (cluster / "PG_VERSION").is_file():
            if cluster.exists() and any(cluster.iterdir()):
                raise RuntimeError("PostgreSQL data directory is not empty; refusing to initialize it.")
            cluster.parent.mkdir(parents=True, exist_ok=True)
            print("Initializing local PostgreSQL...", flush=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as secret:
                secret.write(password + "\n")
                secret_path = Path(secret.name)
            try:
                run([str(binaries / "initdb.exe"), "-D", str(cluster), "-U", username,
                     "--pwfile", str(secret_path), "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C"])
            finally:
                secret_path.unlink(missing_ok=True)
        print("Starting local PostgreSQL...", flush=True)
        run([str(binaries / "pg_ctl.exe"), "-D", str(cluster), "-l", str(cluster.parent / "postgresql.log"),
             "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "30", "start"])
        # CREATE DATABASE cannot run inside a transaction.
        with psycopg.connect(make_conninfo(dsn, dbname="postgres", connect_timeout=3), autocommit=True) as db:
            name = settings.get("dbname", "azurai")
            if not db.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(make_conninfo(dsn, connect_timeout=3)) as db:
        db.execute("SELECT 1")
    print("PostgreSQL ready.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, psycopg.Error, OSError, ValueError) as exc:
        message = str(exc)
        password = dotenv_values(ROOT / ".env").get("AZURAI_POSTGRES_PASSWORD")
        if password:
            message = message.replace(password, "[redacted]")
        print(f"Database startup failed: {message}", flush=True)
        raise SystemExit(1) from None
