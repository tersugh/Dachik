"""SQLite engine, migration, and transaction lifecycle."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Owns the SQLite engine and short-lived transactional sessions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        event.listen(self.engine, "connect", self._configure_connection)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_connection(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[2] / "migrations"))
        config.attributes["connection"] = self.engine
        command.upgrade(config, "head")

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
