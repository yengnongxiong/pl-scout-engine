from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.fotmob import FotMobAdapter, parse_possession, snapshot_name

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "fotmob"
FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
SEASON = "2025-26"
FIXTURE = FIXTURE_DIR / f"synthetic_{snapshot_name(SEASON)}"
TOLERANCE = load_config(PROJECT_ROOT / "config").settings.ingest.possession_sum_tolerance


def _snapshots(tmp_path: Path, body: bytes) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("fotmob", snapshot_name(SEASON), body)]


@pytest.fixture
def adapter() -> FotMobAdapter:
    return FotMobAdapter([SEASON], TOLERANCE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("58%", 0.58), ("58", 0.58), (58, 0.58), (0.58, 0.58), ("100%", 1.0), (" 42 % ", 0.42)],
)
def test_parse_possession_formats(raw: object, expected: float) -> None:
    assert parse_possession(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, float("nan"), "", "%"])
def test_parse_possession_missing(raw: object) -> None:
    assert parse_possession(raw) is None


@pytest.mark.parametrize("raw", ["abc", "150%", -5])
def test_parse_possession_invalid(raw: object) -> None:
    with pytest.raises(DataValidationError):
        parse_possession(raw)


def test_parse_rows_per_team(adapter: FotMobAdapter, tmp_path: Path) -> None:
    df = adapter.parse(_snapshots(tmp_path, FIXTURE.read_bytes()))
    assert len(df) == 6
    rovers = df[(df["team_name"] == "Synthetic Rovers") & (df["date"] == date(2025, 8, 16))]
    row = rovers.iloc[0]
    assert row["possession_share"] == pytest.approx(0.58)
    assert row["opp_possession_share"] == pytest.approx(0.42)
    assert row["opponent_name"] == "Fixture Town"
    assert set(df["source"]) == {"fotmob"}


def test_missing_possession_stays_null(adapter: FotMobAdapter, tmp_path: Path) -> None:
    df = adapter.parse(_snapshots(tmp_path, FIXTURE.read_bytes()))
    late = df[df["date"] == date(2025, 8, 30)]
    assert len(late) == 2
    assert late["possession_share"].isna().all()
    assert late["opp_possession_share"].isna().all()


def test_possession_must_sum_to_one(adapter: FotMobAdapter, tmp_path: Path) -> None:
    body = FIXTURE.read_bytes().replace(b",42%,", b",30%,")
    with pytest.raises(DataValidationError, match="sums to"):
        adapter.parse(_snapshots(tmp_path, body))


def test_game_needs_two_team_rows(adapter: FotMobAdapter, tmp_path: Path) -> None:
    lines = FIXTURE.read_bytes().decode().splitlines()
    body = ("\n".join(lines[:2] + lines[3:]) + "\n").encode()
    with pytest.raises(DataValidationError, match="1 team rows"):
        adapter.parse(_snapshots(tmp_path, body))


def test_schema_changed_fails_loudly(adapter: FotMobAdapter, tmp_path: Path) -> None:
    body = FIXTURE.read_bytes().replace(b"Ball possession", b"Possession", 1)
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, body))


def test_missing_snapshot_fails(adapter: FotMobAdapter) -> None:
    with pytest.raises(DataValidationError, match="missing"):
        adapter.parse([])


class FakeReader:
    def __init__(self, empty: bool = False) -> None:
        self.empty = empty
        self.calls: list[dict[str, Any]] = []

    def read_team_match_stats(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        if self.empty:
            return pd.DataFrame()
        return pd.read_csv(FIXTURE).set_index(["league", "season", "game", "team"])


def _client() -> PoliteClient:
    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    return PoliteClient("fotmob", cfg, bucket=TokenBucket(1e9, 1e9))


def test_fetch_round_trip(tmp_path: Path) -> None:
    reader = FakeReader()
    adapter = FotMobAdapter([SEASON], TOLERANCE, reader_factory=lambda s: reader)
    with _client() as client:
        snaps = adapter.fetch(client, SnapshotStore(tmp_path))
        assert client.requests_made == 1
    assert reader.calls == [{"stat_type": "Top stats"}]
    assert len(adapter.parse(snaps)) == 6


def test_fetch_empty_is_failure(tmp_path: Path) -> None:
    adapter = FotMobAdapter([SEASON], TOLERANCE, reader_factory=lambda s: FakeReader(True))
    with _client() as client, pytest.raises(SourceUnavailableError):
        adapter.fetch(client, SnapshotStore(tmp_path))
