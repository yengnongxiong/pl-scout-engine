import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.espn import EspnAdapter, parse_possession, snapshot_name

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "espn" / "synthetic_2025-26_scoreboards.json"
FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
SEASON = "2025-26"
CFG = load_config(PROJECT_ROOT / "config").settings.ingest
TOLERANCE = CFG.possession_sum_tolerance
BASE = "https://espn.test/soccer/eng.1/"


def _payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text())
    return data


def _snapshots(tmp_path: Path, payload: dict[str, Any]) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("espn", snapshot_name(SEASON), json.dumps(payload).encode())]


@pytest.fixture
def adapter() -> EspnAdapter:
    return EspnAdapter(BASE, [SEASON], TOLERANCE)


@pytest.mark.parametrize(
    ("raw", "expected"), [("43.4", 0.434), (43.4, 0.434), ("58%", 0.58), ("100", 1.0), (0, 0.0)]
)
def test_parse_possession_formats(raw: object, expected: float) -> None:
    assert parse_possession(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, float("nan"), "", "%"])
def test_parse_possession_missing(raw: object) -> None:
    assert parse_possession(raw) is None


@pytest.mark.parametrize("raw", ["abc", "150", -5])
def test_parse_possession_invalid(raw: object) -> None:
    with pytest.raises(DataValidationError):
        parse_possession(raw)


def test_parse_rows_per_team(adapter: EspnAdapter, tmp_path: Path) -> None:
    df = adapter.parse(_snapshots(tmp_path, _payload()))
    assert len(df) == 6  # three finished matches x two teams; the postponed one is skipped
    row = df[(df["espn_event_id"] == 990001) & df["is_home"]].iloc[0]
    assert row["team_name"] == "Synthetic Rovers" and row["opponent_name"] == "Fixture Town"
    assert row["possession_share"] == pytest.approx(0.58)
    assert row["opp_possession_share"] == pytest.approx(0.42)
    assert row["date"] == date(2025, 8, 16)
    assert row["kickoff"] == datetime(2025, 8, 16, 14, tzinfo=UTC)
    away = df[(df["espn_event_id"] == 990001) & ~df["is_home"]].iloc[0]
    assert away["team_name"] == "Fixture Town"
    assert set(df["source"]) == {"espn"}
    assert (df["fetched_at"] == FETCHED_AT).all()
    assert 990004 not in set(df["espn_event_id"])


def test_missing_possession_stays_null(adapter: EspnAdapter, tmp_path: Path) -> None:
    df = adapter.parse(_snapshots(tmp_path, _payload()))
    late = df[df["espn_event_id"] == 990003]
    assert len(late) == 2
    assert late["possession_share"].isna().all()
    assert late["opp_possession_share"].isna().all()


def test_possession_must_sum_to_one(adapter: EspnAdapter, tmp_path: Path) -> None:
    payload = _payload()
    away = payload["days"]["20250816"]["events"][0]["competitions"][0]["competitors"][1]
    away["statistics"][0]["displayValue"] = "30.0"
    with pytest.raises(DataValidationError, match="sums to"):
        adapter.parse(_snapshots(tmp_path, payload))


def test_event_needs_a_home_and_an_away_side(adapter: EspnAdapter, tmp_path: Path) -> None:
    payload = _payload()
    competitors = payload["days"]["20250816"]["events"][0]["competitions"][0]["competitors"]
    competitors[1]["homeAway"] = "home"
    with pytest.raises(DataValidationError, match="one home and one away"):
        adapter.parse(_snapshots(tmp_path, payload))


def test_schema_changed_fails_loudly(adapter: EspnAdapter, tmp_path: Path) -> None:
    payload = _payload()
    del payload["days"]["20250823"]["events"][0]["competitions"]
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, payload))


def test_missing_snapshot_fails(adapter: EspnAdapter) -> None:
    with pytest.raises(DataValidationError, match="missing"):
        adapter.parse([])


def _client(transport: httpx.MockTransport) -> PoliteClient:
    return PoliteClient("espn", CFG, transport=transport, bucket=TokenBucket(1e9, 1e9))


def _handler(calls: list[str], season_year: int = 2025) -> httpx.MockTransport:
    days = _payload()["days"]

    def handle(request: httpx.Request) -> httpx.Response:
        day = request.url.params["dates"]
        calls.append(day)
        if day == "20250801":
            body = {
                "leagues": [
                    {
                        "season": {"year": season_year},
                        "calendar": _payload()["calendar"],
                    }
                ],
                "events": [],
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json=days[day])

    return httpx.MockTransport(handle)


def test_fetch_requests_each_match_day_up_to_today(tmp_path: Path) -> None:
    calls: list[str] = []
    adapter = EspnAdapter(BASE, [SEASON], TOLERANCE, today=lambda: date(2025, 8, 25))
    with _client(_handler(calls)) as client:
        snaps = adapter.fetch(client, SnapshotStore(tmp_path))
    assert calls == ["20250801", "20250816", "20250823"]  # 30 August is still to come
    assert len(adapter.parse(snaps)) == 4


def test_fetch_rejects_the_wrong_season(tmp_path: Path) -> None:
    adapter = EspnAdapter(BASE, [SEASON], TOLERANCE, today=lambda: date(2026, 6, 1))
    with (
        _client(_handler([], season_year=2024)) as client,
        pytest.raises(DataValidationError, match="season 2024"),
    ):
        adapter.fetch(client, SnapshotStore(tmp_path))


def test_fetch_blocked_host_is_a_source_failure(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, content=b"x" * 100))
    adapter = EspnAdapter(BASE, [SEASON], TOLERANCE)
    with _client(transport) as client, pytest.raises(SourceUnavailableError, match="403"):
        adapter.fetch(client, SnapshotStore(tmp_path))
