from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import DEFAULT_DATABASE_PATH, Settings
from backend.app.database import Database
from backend.app.main import create_app


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "dachik-test.sqlite3"
    assert path.resolve() != DEFAULT_DATABASE_PATH.resolve()
    return path


@pytest.fixture
def database(database_path: Path) -> Iterator[Database]:
    value = Database(database_path)
    value.initialize()
    yield value
    value.dispose()


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(database_path=database_path, runtime_environment="test"))
    with TestClient(app) as test_client:
        yield test_client
