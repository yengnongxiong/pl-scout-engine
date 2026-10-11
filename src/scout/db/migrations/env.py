"""Alembic environment: runs migrations against the warehouse URL from settings."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from scout.config import get_settings
from scout.db.models import Base
from scout.db.session import make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _run(connection: Connection) -> None:
    # Batch mode lets ALTER-style migrations work on SQLite too.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on a connection (reuses one passed in via ``config.attributes``)."""
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        _run(connection)
        return
    engine = make_engine(_url())
    try:
        with engine.connect() as conn:
            if conn.dialect.name != "sqlite":
                with conn.begin():
                    _run(conn)
                return
            # Batch migrations rebuild a SQLite table (copy, drop, rename), and SQLite will not
            # drop a table other tables reference while foreign keys are on. They are switched
            # off for the migration (the pragma is ignored inside a transaction), every
            # reference is checked before committing, and they are switched back on.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
            with conn.begin():
                _run(conn)
                broken = conn.exec_driver_sql("PRAGMA foreign_key_check").all()
                if broken:
                    raise RuntimeError(f"migration left broken foreign keys: {broken[:5]}")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
