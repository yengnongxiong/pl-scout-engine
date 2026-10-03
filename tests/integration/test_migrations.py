from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from scout.config import PROJECT_ROOT
from scout.db.models import Base, DimPlayer, DimSeason, FactMarketValue
from scout.db.session import make_engine, make_session_factory


def _alembic(url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_matches_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'wh' / 'scout.db'}"
    command.upgrade(_alembic(url), "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables
    engine.dispose()


def test_downgrade_base_drops_everything(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'scout.db'}"
    cfg = _alembic(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = make_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_foreign_keys_enforced_and_round_trip() -> None:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    now = datetime(2026, 9, 1, tzinfo=UTC)
    with session_factory() as session:
        session.add(DimSeason(season_id="2026-27", is_current=True))
        player = DimPlayer(canonical_name="Alex Testman", fpl_code=500011)
        session.add(player)
        session.flush()
        session.add(
            FactMarketValue(
                player_id=player.player_id,
                value_eur=3_000_000_000,  # needs BigInteger
                is_stale=False,
                source="transfermarkt",
                fetched_at=now,
            )
        )
        session.commit()
        stored = session.get(FactMarketValue, 1)
        assert stored is not None and stored.value_eur == 3_000_000_000
    with session_factory() as session:
        session.add(
            FactMarketValue(player_id=999, is_stale=False, source="override", fetched_at=now)
        )
        with pytest.raises(IntegrityError):
            session.commit()
