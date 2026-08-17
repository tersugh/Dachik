from pathlib import Path

from sqlalchemy import inspect, text

from backend.app.database import Database

EXPECTED_TABLES = {
    "alembic_version",
    "applications",
    "application_usage",
    "collector_runs",
    "counter_observations",
    "counter_series",
    "data_audit_experiments",
    "data_bundles",
    "devices",
    "isp_balance_snapshots",
    "measurement_discontinuities",
    "traffic_sources",
    "usage_intervals",
}


def test_initialize_applies_migrations_and_sqlite_policy(database_path: Path) -> None:
    database = Database(database_path)

    database.initialize()
    database.initialize()

    assert database_path.is_file()
    assert set(inspect(database.engine).get_table_names()) >= EXPECTED_TABLES
    with database.engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

    assert revision == "15ac772ee7c5"
    assert foreign_keys == 1
    assert journal_mode == "wal"
