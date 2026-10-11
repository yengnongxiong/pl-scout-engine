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


def test_upgrade_keeps_rows_that_reference_rebuilt_tables(tmp_path: Path) -> None:
    # SQLite batch migrations rebuild a table (copy, drop, rename). With foreign keys on,
    # dropping dim_match failed while fact tables referenced it: an empty database (the
    # test above) never showed it, the owner's warehouse did (migration 0005).
    url = f"sqlite:///{tmp_path / 'scout.db'}"
    cfg = _alembic(url)
    command.upgrade(cfg, "0004")
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO dim_season (season_id, is_current) VALUES ('2026-27', 1)")
        conn.exec_driver_sql("INSERT INTO dim_team (team_id, name) VALUES (1, 'A'), (2, 'B')")
        conn.exec_driver_sql(
            "INSERT INTO dim_match (match_id, season_id, home_team_id, away_team_id, "
            "fotmob_game) VALUES (7, '2026-27', 1, 2, 'g')"
        )
        conn.exec_driver_sql(
            "INSERT INTO fact_team_match (match_id, team_id, possession, source, fetched_at) "
            "VALUES (7, 1, 0.5, 'understat', '2026-09-01')"
        )
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT match_id, espn_event_id FROM dim_match").all() == [
            (7, None)
        ]
        assert conn.exec_driver_sql("SELECT count(*) FROM fact_team_match").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
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
