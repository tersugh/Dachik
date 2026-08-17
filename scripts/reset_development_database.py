"""Back up and recreate only Dachik's normal development database."""

import argparse
import shutil
import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import DEFAULT_DATABASE_PATH
from backend.app.database import Database


def normal_backend_is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="confirm the recoverable reset")
    args = parser.parse_args()
    database_path = DEFAULT_DATABASE_PATH.expanduser().resolve()
    expected_parent = (Path.home() / "Library" / "Application Support" / "Dachik").resolve()
    print(f"Resolved development database: {database_path}")
    if database_path.parent != expected_parent or database_path.name != "dachik.sqlite3":
        parser.error("Refusing to reset an unexpected database path")
    if normal_backend_is_running():
        parser.error("Stop the FastAPI backend on 127.0.0.1:8765 before resetting")
    if not args.confirm:
        parser.error("Stop the backend, inspect the path above, then rerun with --confirm")

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
    backup_directory = expected_parent / "backups" / f"reset-{timestamp}"
    backup_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    for source in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        if source.exists():
            shutil.move(str(source), backup_directory / source.name)
    print(f"Backup directory: {backup_directory}")

    database = Database(database_path)
    try:
        database.initialize()
    finally:
        database.dispose()
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    print(f"Alembic revision: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
