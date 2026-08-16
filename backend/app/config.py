"""Environment-driven settings for the local service."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATABASE_PATH = (
    Path.home() / "Library" / "Application Support" / "Dachik" / "dachik.sqlite3"
)


def _cors_origins_from_environment() -> tuple[str, ...]:
    raw_origins = os.getenv("DACHIK_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings, populated from environment variables by default."""

    database_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("DACHIK_DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
        ).expanduser()
    )
    cors_origins: tuple[str, ...] = field(default_factory=_cors_origins_from_environment)
