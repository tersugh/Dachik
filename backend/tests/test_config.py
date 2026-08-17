from pathlib import Path

import pytest

from backend.app.config import (
    BROWSER_VERIFICATION_ENVIRONMENT,
    DEFAULT_DATABASE_PATH,
    Settings,
)


def test_browser_verification_refuses_normal_development_database() -> None:
    with pytest.raises(ValueError, match="must not use the normal Dachik development database"):
        Settings(
            database_path=DEFAULT_DATABASE_PATH,
            runtime_environment=BROWSER_VERIFICATION_ENVIRONMENT,
        )


def test_browser_verification_accepts_separate_temporary_database(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "browser-verification.sqlite3",
        runtime_environment=BROWSER_VERIFICATION_ENVIRONMENT,
    )

    assert settings.database_path != DEFAULT_DATABASE_PATH
