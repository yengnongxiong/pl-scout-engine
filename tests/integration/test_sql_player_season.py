"""``player_season.sql`` checked against its pandas twin on a fixture-built warehouse."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.queries import load_sql, player_season_totals
from scout.db.session import make_engine
from scout.errors import ConfigError
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
STATS = [
    "goals", "assists", "xg", "npxg", "xa", "shots", "key_passes", "xg_chain", "xg_buildup",
    "tackles", "recoveries", "cbi", "def_contribution", "xgc_on_pitch", "yellow_cards",
    "red_cards",
]  # fmt: skip
KEYS = ["player_id", "season_id", "team_id", "source"]


def pandas_twin(facts: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Reference implementation: same grouping, SQL null semantics (min_count=1)."""
    df = facts.merge(matches[["match_id", "season_id"]], on="match_id")
    df["start_flag"] = df["started"].map(lambda v: None if pd.isna(v) else int(bool(v)))
    grouped = df.groupby(KEYS, sort=True)
    out = grouped.size().rename("matches").to_frame()
    for col in ["minutes", "start_flag", *STATS]:
        out[col] = grouped[col].sum(min_count=1)
    return out.rename(columns={"start_flag": "starts"}).reset_index()


@pytest.fixture
def engine_and_tables(tmp_path: Path) -> Iterator[tuple[Engine, pd.DataFrame, pd.DataFrame]]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    engine = make_engine(settings.database_url)
    facts = pd.read_sql_table("fact_player_match", engine)
    matches = pd.read_sql_table("dim_match", engine)
    yield engine, facts, matches
    engine.dispose()


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(KEYS).reset_index(drop=True)
    for col in out.columns:
        if col not in ("season_id", "source"):
            out[col] = pd.to_numeric(out[col]).astype(float)
    return out


def test_sql_matches_pandas_twin(
    engine_and_tables: tuple[Engine, pd.DataFrame, pd.DataFrame],
) -> None:
    engine, facts, matches = engine_and_tables
    sql = _numeric(player_season_totals(engine))
    twin = _numeric(pandas_twin(facts, matches))
    assert list(sql.columns) == list(twin.columns)
    assert len(sql) > 0
    pd.testing.assert_frame_equal(sql, twin, check_exact=False, rtol=1e-9)


def test_totals_keep_source_specific_nulls(
    engine_and_tables: tuple[Engine, pd.DataFrame, pd.DataFrame],
) -> None:
    engine, _, _ = engine_and_tables
    totals = player_season_totals(engine)
    fpl = totals[(totals["source"] == "fpl") & (totals["season_id"] == "2026-27")]
    assert sorted(fpl["minutes"]) == [95, 180]  # Bo 65+30, Alex 90+90
    understat = totals[totals["source"] == "understat"]
    assert understat["tackles"].isna().all()  # Understat has no tackles: NULL, not 0
    assert understat["npxg"].notna().all()
    vaastav = totals[totals["source"] == "vaastav"]
    assert set(vaastav["season_id"]) == {"2025-26"}


def test_unknown_sql_file() -> None:
    with pytest.raises(ConfigError):
        load_sql("does_not_exist")


def test_sql_comments_do_not_declare_bind_parameters() -> None:
    import re

    sql_dir = PROJECT_ROOT / "src" / "scout" / "db" / "sql"
    for path in sql_dir.glob("*.sql"):
        for line in path.read_text().splitlines():
            if line.lstrip().startswith("--"):
                assert not re.search(r"(?<!:):[a-z_]+", line), f"{path.name}: {line}"
