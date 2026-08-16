from pathlib import Path

from backend.app.database import SCHEMA_VERSION, Database


def test_initialize_creates_configured_database(database_path: Path) -> None:
    database = Database(database_path)

    database.initialize()

    assert database_path.is_file()
    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert version == SCHEMA_VERSION
    assert foreign_keys == 1
    assert journal_mode == "wal"
