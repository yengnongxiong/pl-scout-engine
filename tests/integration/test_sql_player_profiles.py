"""``player_profiles.sql`` and ``market_values.sql`` against pandas twins on fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.queries import latest_market_values, player_profiles
from scout.db.session import make_engine
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
DATES = ["birth_date", "contract_expiry", "status_as_of", "tm_last_updated", "fetched_at"]


def _latest(df: pd.DataFrame, keys: list[str], order: list[str]) -> pd.DataFrame:
    """First row per ``keys`` after sorting ``order`` descending (ROW_NUMBER = 1)."""
    ranked = df.sort_values([*keys, *order], ascending=[True] * len(keys) + [False] * len(order))
    return ranked.groupby(keys, sort=True).head(1)


def profiles_twin(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    current = set(t["dim_season"].loc[t["dim_season"]["is_current"].astype(bool), "season_id"])
    matches = t["dim_match"][["match_id", "season_id", "kickoff"]]
    df = t["fact_player_match"].merge(matches, on="match_id")
    df = df[(df["source"] == "fpl") & df["season_id"].isin(current)]
    df = df.assign(has_kickoff=df["kickoff"].notna().astype(int))
    latest = _latest(df, ["player_id"], ["has_kickoff", "kickoff", "match_id"])
    out = latest[["player_id", "team_id"]].rename(columns={"team_id": "current_team_id"})
    minutes = df.groupby("player_id")["minutes"].sum(min_count=1).rename("season_minutes")
    status = _latest(t["fact_player_status"], ["player_id"], ["fetched_at"])
    status = status[["player_id", "fpl_status", "chance_of_playing", "contract_expiry",
                     "fetched_at"]].rename(columns={"fetched_at": "status_as_of"})  # fmt: skip
    players = t["dim_player"][["player_id", "canonical_name", "position_group", "birth_date"]]
    out = players.merge(out, on="player_id").merge(minutes.reset_index(), on="player_id")
    return out.merge(status, on="player_id", how="left")


def market_twin(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    mv = t["fact_market_value"]
    mv = mv[mv["value_eur"].notna() & mv["tm_last_updated"].notna()]
    latest = _latest(mv, ["player_id", "source"], ["tm_last_updated", "fetched_at", "id"])
    cols = ["player_id", "source", "value_eur", "tm_last_updated", "is_stale", "reason"]
    return latest[[*cols, "fetched_at"]]


@pytest.fixture
def warehouse(tmp_path: Path) -> Iterator[tuple[Engine, dict[str, pd.DataFrame]]]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    engine = make_engine(settings.database_url)
    names = ["dim_season", "dim_match", "dim_player", "fact_player_match",
             "fact_player_status", "fact_market_value"]  # fmt: skip
    yield engine, {n: pd.read_sql_table(n, engine) for n in names}
    engine.dispose()


def _norm(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    out = df.sort_values(keys).reset_index(drop=True)
    for col in out.columns:
        if col in DATES:
            out[col] = pd.to_datetime(out[col], utc=True)
        elif out[col].dtype.kind in "biufc" or col in ("chance_of_playing", "is_stale"):
            out[col] = pd.to_numeric(out[col]).astype(float)
        else:
            out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out


def test_player_profiles_match_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    sql = _norm(player_profiles(engine), ["player_id"])
    twin = _norm(profiles_twin(tables), ["player_id"])
    assert list(sql.columns) == list(twin.columns)
    pd.testing.assert_frame_equal(sql, twin, check_dtype=False)
    by_name = {r["canonical_name"]: r for r in player_profiles(engine).to_dict(orient="records")}
    # Only players with current-season FPL rows: Alex (90 + 90) and Bo (65 + 30).
    assert set(by_name) == {"Alex Testman", "Bo Fakeson"}
    assert by_name["Alex Testman"]["season_minutes"] == 180
    assert (by_name["Bo Fakeson"]["fpl_status"], by_name["Bo Fakeson"]["chance_of_playing"]) == (
        "d",
        75,
    )


def test_market_values_match_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    keys = ["player_id", "source"]
    sql = _norm(latest_market_values(engine), keys)
    twin = _norm(market_twin(tables), keys)
    assert list(sql.columns) == list(twin.columns)
    pd.testing.assert_frame_equal(sql, twin, check_dtype=False)
    # The fixture's second player has no valuation history: no value, no row.
    assert len(sql) == 1
    row = sql.iloc[0]
    assert (row["source"], row["value_eur"]) == ("transfermarkt", 32_000_000)
    assert row["tm_last_updated"].date().isoformat() == "2026-06-10"
