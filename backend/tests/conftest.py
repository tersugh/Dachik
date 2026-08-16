from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "dachik-test.sqlite3"


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(database_path=database_path))
    with TestClient(app) as test_client:
        yield test_client
