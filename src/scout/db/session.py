"""Engine and session factory for the warehouse."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def _sqlite_foreign_keys(dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
    # SQLite ignores foreign keys unless asked; Postgres always enforces them.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(database_url: str) -> Engine:
    """Create an engine; for file-backed SQLite, ensure the parent directory exists."""
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False)
