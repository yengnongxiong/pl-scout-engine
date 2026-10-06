"""Postgres parity (stretch S3): the same fixture build gives the same answers as SQLite.

Runs only when ``SCOUT_TEST_POSTGRES_URL`` points at an empty, disposable Postgres database
(the CI ``postgres`` job, or ``docker compose up -d db`` locally); the public schema is
dropped and recreated. Every analytical query, the diagnosis, the shortlist, the backtest
and the API are compared with the SQLite build of the same fixtures.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text

from scout.api.main import create_app
from scout.config import PROJECT_ROOT, Settings
from scout.db import queries
from scout.db.models import Base
from scout.db.session import make_engine
from scout.engines.backtest import run_backtest
from scout.engines.diagnosis import diagnose, find_team
from scout.engines.recommend import recommend
from scout.pipeline import build_all
from tests.integration.test_build import _seed
from tests.integration.test_diagnose import _config

PG_URL = os.environ.get("SCOUT_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="SCOUT_TEST_POSTGRES_URL not set")
AS_OF = date(2026, 10, 1)


def _reset(url: str) -> None:
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _build(tmp: Path, url: str) -> Settings:
    settings = Settings(data_dir=tmp / "data", database_url=url)
    _seed(settings.data_dir)
    build_all(settings, _config())
    return settings


@pytest.fixture(scope="module")
def warehouses(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Settings, Settings]]:
    assert PG_URL is not None
    _reset(PG_URL)
    lite = _build(
        tmp_path_factory.mktemp("lite"), f"sqlite:///{tmp_path_factory.mktemp('db')}/w.db"
    )
    pg = _build(tmp_path_factory.mktemp("pg"), PG_URL)
    yield lite, pg
    _reset(PG_URL)


def _norm(value: object) -> object:
    """Backend-neutral value: SQLite returns text dates and 0/1 flags, Postgres native types."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 9)
    if isinstance(value, (datetime, pd.Timestamp)):
        ts = pd.Timestamp(value)
        return (ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            ts = pd.Timestamp(value)
        except ValueError:
            return value
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return (ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts).isoformat()
        return value
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [{str(k): _norm(v) for k, v in r.items()} for r in frame.to_dict(orient="records")]


QUERIES = {
    "player_season": lambda e: queries.player_season_totals(e),
    "defensive_padj": lambda e: queries.defensive_padj_totals(
        e, even_share=0.5, clip_min=0.67, clip_max=1.5
    ),
    "standings_previous": lambda e: queries.standings(e, "2025-26"),
    "standings_current": lambda e: queries.standings(e, "2026-27"),
    "club_players": lambda e: queries.club_players(e),
    "player_features_blended": lambda e: queries.player_features(e, "blended"),
    "player_features_current": lambda e: queries.player_features(e, "current"),
    "team_season_understat": lambda e: queries.team_season_totals(e, "understat"),
    "team_season_fotmob": lambda e: queries.team_season_totals(e, "fotmob"),
    "player_profiles": lambda e: queries.player_profiles(e),
    "market_values": lambda e: queries.latest_market_values(e),
    "market_value_history": lambda e: queries.market_value_history(e),
    "season_bounds": lambda e: queries.season_bounds(e),
}


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_every_query_matches_sqlite(warehouses: tuple[Settings, Settings], name: str) -> None:
    lite, pg = (make_engine(s.database_url) for s in warehouses)
    try:
        left, right = QUERIES[name](lite), QUERIES[name](pg)
    finally:
        lite.dispose()
        pg.dispose()
    assert list(left.columns) == list(right.columns)
    assert _records(left) == _records(right)


def _engines(warehouses: tuple[Settings, Settings]) -> tuple[Engine, Engine]:
    return make_engine(warehouses[0].database_url), make_engine(warehouses[1].database_url)


def test_engines_match_sqlite(warehouses: tuple[Settings, Settings]) -> None:
    config = _config()
    lite, pg = _engines(warehouses)
    try:
        team = find_team(pg, "Synthetic Rovers", config.team_aliases.aliases)
        assert (
            team.team_id == find_team(lite, "Synthetic Rovers", config.team_aliases.aliases).team_id
        )
        assert diagnose(pg, team.team_id, config, as_of=AS_OF) == diagnose(
            lite, team.team_id, config, as_of=AS_OF
        )
        assert recommend(pg, team.team_id, config, position_group="ST", as_of=AS_OF) == recommend(
            lite, team.team_id, config, position_group="ST", as_of=AS_OF
        )
        assert run_backtest(pg, config).__dict__ == run_backtest(lite, config).__dict__
    finally:
        lite.dispose()
        pg.dispose()


def test_api_matches_sqlite(warehouses: tuple[Settings, Settings]) -> None:
    lite, pg = warehouses
    with TestClient(create_app(lite, _config())) as a, TestClient(create_app(pg, _config())) as b:
        teams = a.get("/teams").json()
        assert teams == b.get("/teams").json()
        for path in (
            f"/teams/{teams[0]['team_id']}/diagnosis",
            f"/teams/{teams[0]['team_id']}/recommendations",
            "/players/search?q=bo",
            "/meta/methodology",
        ):
            assert a.get(path).json() == b.get(path).json(), path
        assert b.get("/health").json()["warehouse_version"] is not None


def test_migrations_round_trip_on_postgres(warehouses: tuple[Settings, Settings]) -> None:
    assert PG_URL is not None
    _reset(PG_URL)  # the module fixture rebuilds nothing after this test
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(cfg, "head")
    engine = make_engine(PG_URL)
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
