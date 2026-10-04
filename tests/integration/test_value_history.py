"""Valuation history and season bounds on a fixture build that includes the datasets export."""

import gzip
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.queries import market_value_history, season_bounds
from scout.db.session import make_engine
from scout.ingest.base import SnapshotStore
from scout.ingest.transfermarkt import DATASETS_PLAYERS, DATASETS_SOURCE, DATASETS_VALUATIONS
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
FIX = PROJECT_ROOT / "tests" / "fixtures" / "transfermarkt"


@pytest.fixture
def warehouse(tmp_path: Path) -> Iterator[tuple[Engine, dict[str, pd.DataFrame]]]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    store = SnapshotStore(settings.data_dir / "raw", clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    for name, fixture in (
        (DATASETS_PLAYERS, "players"),
        (DATASETS_VALUATIONS, "player_valuations"),
    ):
        body = gzip.compress((FIX / f"synthetic_datasets_{fixture}.csv").read_bytes())
        store.write(DATASETS_SOURCE, name, body)
    build_warehouse(settings, CONFIG)
    engine = make_engine(settings.database_url)
    tables = {n: pd.read_sql_table(n, engine) for n in ("fact_market_value", "dim_match")}
    yield engine, tables
    engine.dispose()


def test_history_is_stored_alongside_the_live_value(
    warehouse: tuple[Engine, dict[str, pd.DataFrame]],
) -> None:
    engine, _ = warehouse
    history = market_value_history(engine)
    # Alex: two stale datasets points plus the live value; nothing else has a value.
    by_source = history.groupby("source")["tm_last_updated"].apply(list).to_dict()
    assert by_source == {
        "transfermarkt": [date(2026, 6, 10)],
        "transfermarkt_datasets": [date(2025, 6, 1), date(2026, 5, 20)],
    }
    assert history["player_id"].nunique() == 1
    stale = history[history["source"] == "transfermarkt_datasets"]
    assert stale["is_stale"].astype(bool).all()


def test_history_matches_pandas_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    mv = tables["fact_market_value"]
    twin = mv[mv["value_eur"].notna() & mv["tm_last_updated"].notna()].sort_values(
        ["player_id", "tm_last_updated", "source"]
    )[["player_id", "source", "value_eur", "tm_last_updated", "is_stale", "fetched_at"]]
    sql = market_value_history(engine)
    assert list(sql.columns) == list(twin.columns)
    assert list(sql["value_eur"]) == list(twin["value_eur"])
    assert [str(d) for d in sql["tm_last_updated"]] == [
        str(pd.Timestamp(d).date()) for d in twin["tm_last_updated"]
    ]


def test_season_bounds_match_pandas_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    m = tables["dim_match"].dropna(subset=["kickoff"])
    grouped = m.groupby("season_id")["kickoff"]
    twin = pd.DataFrame(
        {"first_kickoff": grouped.min(), "last_kickoff": grouped.max(), "matches": grouped.size()}
    ).reset_index()
    sql = season_bounds(engine)
    assert list(sql["season_id"]) == list(twin["season_id"])
    assert list(sql["matches"]) == list(twin["matches"])
    for col in ("first_kickoff", "last_kickoff"):
        assert list(sql[col]) == list(pd.to_datetime(twin[col], utc=True))
    assert len(sql) >= 2  # current season (FPL) and last season (vaastav)
