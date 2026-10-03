import gzip
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT
from scout.errors import DataValidationError
from scout.ingest.base import RawSnapshot, SnapshotStore
from scout.ingest.transfermarkt import (
    DATASETS_PLAYERS,
    DATASETS_VALUATIONS,
    TransfermarktDatasetsAdapter,
    load_market_value_overrides,
)

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "transfermarkt"
FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _gz(name: str) -> bytes:
    return gzip.compress((FIXTURE_DIR / f"synthetic_datasets_{name}.csv").read_bytes())


def _snapshots(tmp_path: Path, players: bytes, valuations: bytes) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [
        store.write("transfermarkt_datasets", DATASETS_PLAYERS, players),
        store.write("transfermarkt_datasets", DATASETS_VALUATIONS, valuations),
    ]


@pytest.fixture
def adapter() -> TransfermarktDatasetsAdapter:
    return TransfermarktDatasetsAdapter("https://datasets.test/data", "GB1")


def test_snapshot_rows_are_pl_only_and_stale(
    adapter: TransfermarktDatasetsAdapter, tmp_path: Path
) -> None:
    df = adapter.parse(_snapshots(tmp_path, _gz("players"), _gz("player_valuations")))
    assert set(df["tm_player_id"]) == {"880011", "880015"}  # ES1 player excluded
    assert df["is_stale"].all()
    assert set(df["source"]) == {"transfermarkt_datasets"}
    alex = df.set_index("tm_player_id").loc["880011"]
    assert alex["value_eur"] == 30_000_000  # latest valuation wins
    assert alex["tm_last_updated"] == date(2026, 5, 20)
    assert alex["birth_date"] == date(1998, 3, 14)
    assert alex["tm_position"] == "Centre-Back"


def test_player_without_valuation_has_null_value(
    adapter: TransfermarktDatasetsAdapter, tmp_path: Path
) -> None:
    df = adapter.parse(_snapshots(tmp_path, _gz("players"), _gz("player_valuations")))
    eli = df.set_index("tm_player_id").loc["880015"]
    assert pd.isna(eli["value_eur"]) and pd.isna(eli["tm_last_updated"])
    assert pd.isna(eli["contract_expiry"])


def test_datasets_schema_changed(adapter: TransfermarktDatasetsAdapter, tmp_path: Path) -> None:
    bad = gzip.compress(b"player_id,when,market_value_in_eur\n1,2026-01-01,5\n")
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, _gz("players"), bad))


def test_datasets_not_gzip_fails(adapter: TransfermarktDatasetsAdapter, tmp_path: Path) -> None:
    with pytest.raises(DataValidationError, match="gzipped"):
        adapter.parse(_snapshots(tmp_path, b"<html>blocked</html>", _gz("player_valuations")))


def test_committed_overrides_file_loads_empty() -> None:
    df = load_market_value_overrides(PROJECT_ROOT / "data/overrides/market_value_overrides.csv")
    assert df.empty
    assert "tm_last_updated" in df.columns


def test_override_rows_parse(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "tm_player_id,value_eur,tm_last_updated,reason,date\n"
        "880011,35000000,2026-09-15,TM page updated after last scrape,2026-09-20\n"
        "880013,€800k,15.09.2026,Missing from squad API,2026-09-20\n"
    )
    df = load_market_value_overrides(path).set_index("tm_player_id")
    assert df.loc["880011", "value_eur"] == 35_000_000
    assert df.loc["880013", "value_eur"] == 800_000
    assert df.loc["880013", "tm_last_updated"] == date(2026, 9, 15)
    assert set(df["source"]) == {"override"}
    assert df.loc["880011", "fetched_at"] == datetime(2026, 9, 20, tzinfo=UTC)


def test_override_without_reason_rejected(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(
        "tm_player_id,value_eur,tm_last_updated,reason,date\n1,5,2026-09-15,,2026-09-20\n"
    )
    with pytest.raises(DataValidationError, match="line 2"):
        load_market_value_overrides(path)


def test_override_missing_column_rejected(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text("tm_player_id,value_eur\n1,5\n")
    with pytest.raises(DataValidationError, match="missing columns"):
        load_market_value_overrides(path)
