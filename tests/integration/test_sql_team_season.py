"""``team_season.sql`` checked against its pandas twin on a fixture-built warehouse."""

from collections.abc import Iterator
from pathlib import Path
from typing import get_args

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, Settings, TeamMatchColumn, load_config
from scout.db.build import build_warehouse
from scout.db.queries import team_season_totals
from scout.db.session import make_engine
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
COLUMNS = list(get_args(TeamMatchColumn))
KEYS = ["team_id", "season_id"]


def pandas_twin(facts: pd.DataFrame, matches: pd.DataFrame, source: str) -> pd.DataFrame:
    """Reference implementation: SQL null semantics (SUM of nulls is null, COUNT skips)."""
    df = facts[facts["source"] == source].merge(matches[["match_id", "season_id"]], on="match_id")
    grouped = df.groupby(KEYS, sort=True)
    out = grouped.size().rename("matches").to_frame()
    for col in COLUMNS:
        out[f"{col}_total"] = grouped[col].sum(min_count=1)
        out[f"{col}_matches"] = grouped[col].count()
    out["as_of"] = grouped["fetched_at"].max()
    return out.reset_index()


@pytest.fixture
def engine_and_tables(tmp_path: Path) -> Iterator[tuple[Engine, pd.DataFrame, pd.DataFrame]]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    engine = make_engine(settings.database_url)
    facts = pd.read_sql_table("fact_team_match", engine)
    matches = pd.read_sql_table("dim_match", engine)
    yield engine, facts, matches
    engine.dispose()


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(KEYS).reset_index(drop=True)
    for col in out.columns:
        if col == "as_of":
            out[col] = pd.to_datetime(out[col], utc=True)
        elif col != "season_id":
            out[col] = pd.to_numeric(out[col]).astype(float)
    return out


def test_sql_matches_pandas_twin(
    engine_and_tables: tuple[Engine, pd.DataFrame, pd.DataFrame],
) -> None:
    engine, facts, matches = engine_and_tables
    sql = _numeric(team_season_totals(engine, "understat"))
    twin = _numeric(pandas_twin(facts, matches, "understat"))
    assert list(sql.columns) == list(twin.columns)
    assert len(sql) == 2  # two clubs, one season of Understat fixtures
    pd.testing.assert_frame_equal(sql, twin, check_exact=False, rtol=1e-9)


def test_missing_values_count_in_neither_total_nor_matches(
    engine_and_tables: tuple[Engine, pd.DataFrame, pd.DataFrame],
) -> None:
    engine, _, _ = engine_and_tables
    totals = team_season_totals(engine, "understat")
    teams = pd.read_sql_table("dim_team", engine)
    rovers_id = int(teams.loc[teams["name"] == "Synthetic Rovers", "team_id"].iloc[0])
    rovers = totals[totals["team_id"] == rovers_id].iloc[0]
    # Rovers' away xG is blank in the second fixture game: one match of data, not two.
    assert (rovers["matches"], rovers["xg_matches"]) == (2, 1)
    assert rovers["xg_total"] == pytest.approx(0.45)
    assert rovers["xga_total"] == pytest.approx(0.95)  # 0.95 + a real 0.00
    assert rovers["xga_matches"] == 2
    # FotMob rows carry possession only, so no Understat KPI can come from them.
    assert team_season_totals(engine, "fotmob")["xg_matches"].eq(0).all()
