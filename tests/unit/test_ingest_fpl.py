import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.fpl import (
    BOOTSTRAP,
    FIXTURES,
    FplAdapter,
    FplEvent,
    element_summary_name,
    season_from_events,
)

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "fpl"
FETCHED_AT = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
BASE_URL = "https://fpl.test/api/"


def _payloads() -> dict[str, object]:
    out: dict[str, object] = {
        BOOTSTRAP: json.loads((FIXTURE_DIR / "synthetic_bootstrap_static.json").read_text()),
        FIXTURES: json.loads((FIXTURE_DIR / "synthetic_fixtures.json").read_text()),
    }
    for element_id in (11, 12):
        path = FIXTURE_DIR / f"synthetic_element_summary_{element_id}.json"
        out[element_summary_name(element_id)] = json.loads(path.read_text())
    return out


def _snapshots(tmp_path: Path, payloads: dict[str, object]) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("fpl", name, json.dumps(p).encode()) for name, p in payloads.items()]


@pytest.fixture
def snapshots(tmp_path: Path) -> list[RawSnapshot]:
    return _snapshots(tmp_path, _payloads())


@pytest.fixture
def adapter() -> FplAdapter:
    return FplAdapter(BASE_URL)


def test_season_derived_from_events_not_hardcoded() -> None:
    events = [
        FplEvent(id=2, deadline_time=datetime(2027, 1, 2, tzinfo=UTC), finished=False),
        FplEvent(id=1, deadline_time=datetime(2026, 8, 21, tzinfo=UTC), finished=True),
    ]
    assert season_from_events(events) == "2026-27"
    assert (
        season_from_events([FplEvent(id=1, deadline_time=datetime(2099, 8, 1), finished=False)])
        == "2099-00"
    )
    with pytest.raises(DataValidationError):
        season_from_events([])


def test_teams_keyed_on_code(adapter: FplAdapter, snapshots: list[RawSnapshot]) -> None:
    teams = adapter.parse_teams(snapshots)
    assert list(teams["fpl_code"]) == [9001, 9002]
    assert set(teams["season_id"]) == {"2026-27"}
    assert set(teams["source"]) == {"fpl"}
    assert (teams["fetched_at"] == FETCHED_AT).all()


def test_players_carry_status_and_null_news(
    adapter: FplAdapter, snapshots: list[RawSnapshot]
) -> None:
    players = adapter.parse_players(snapshots).set_index("fpl_code")
    assert players.loc[500012, "fpl_status"] == "d"
    assert players.loc[500012, "chance_of_playing"] == 75
    assert players.loc[500012, "fpl_position"] == "FWD"
    assert players.loc[500012, "team_fpl_code"] == 9002
    # Empty news is missing data, not an empty string (CLAUDE.md rule 2).
    assert players.loc[500011, "news"] is None
    assert pd.isna(players.loc[500011, "chance_of_playing"])


def test_fixtures_keep_unplayed_scores_null(
    adapter: FplAdapter, snapshots: list[RawSnapshot]
) -> None:
    fixtures = adapter.parse_fixtures(snapshots).set_index("fpl_fixture_code")
    assert fixtures.loc[7000101, "home_score"] == 2
    assert pd.isna(fixtures.loc[7000103, "home_score"])
    assert pd.isna(fixtures.loc[7000103, "kickoff"])
    assert fixtures.loc[7000102, "home_team_fpl_code"] == 9002


def test_player_match_rows(adapter: FplAdapter, snapshots: list[RawSnapshot]) -> None:
    pm = adapter.parse(snapshots)
    assert len(pm) == 4
    row = pm[(pm["fpl_code"] == 500012) & (pm["fpl_fixture_code"] == 7000101)].iloc[0]
    # Away at fixture 101 → the player's club is the away team.
    assert row["team_fpl_code"] == 9002
    assert row["opponent_fpl_code"] == 9001
    assert row["xg"] == pytest.approx(0.72)
    assert row["minutes"] == 65
    assert bool(row["started"]) is True
    sub = pm[(pm["fpl_code"] == 500012) & (pm["fpl_fixture_code"] == 7000102)].iloc[0]
    assert bool(sub["started"]) is False
    assert sub["team_fpl_code"] == 9002  # home at fixture 102
    assert set(pm["source"]) == {"fpl"}
    assert pm["fetched_at"].notna().all()


def test_schema_changed_fails_loudly(adapter: FplAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    summary = payloads[element_summary_name(11)]
    assert isinstance(summary, dict)
    del summary["history"][0]["expected_goals"]
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_bootstrap_missing_field_fails(adapter: FplAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    boot = payloads[BOOTSTRAP]
    assert isinstance(boot, dict)
    del boot["elements"][0]["code"]
    with pytest.raises(DataValidationError, match="bootstrap-static"):
        adapter.parse_players(_snapshots(tmp_path, payloads))


def test_unknown_fixture_reference_fails(adapter: FplAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    summary = payloads[element_summary_name(11)]
    assert isinstance(summary, dict)
    summary["history"][0]["fixture"] = 999
    with pytest.raises(DataValidationError, match="unknown fixture"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_missing_snapshot_fails(adapter: FplAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    del payloads[FIXTURES]
    with pytest.raises(DataValidationError, match="missing"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_fetch_snapshots_only_players_with_minutes(adapter: FplAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        if path.endswith("bootstrap-static/"):
            body = payloads[BOOTSTRAP]
        elif path.endswith("fixtures/"):
            body = payloads[FIXTURES]
        else:
            element_id = int(path.rstrip("/").split("/")[-1])
            body = payloads[element_summary_name(element_id)]
        return httpx.Response(200, content=json.dumps(body).encode())

    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    store = SnapshotStore(tmp_path)
    with PoliteClient(
        "fpl", cfg, transport=httpx.MockTransport(handler), bucket=TokenBucket(1e9, 1e9)
    ) as client:
        snaps = adapter.fetch(client, store)
    assert [s.name for s in snaps] == [
        BOOTSTRAP,
        FIXTURES,
        element_summary_name(11),
        element_summary_name(12),
    ]
    assert not any(p.endswith("/13/") for p in requested)  # 0 minutes → not fetched
    assert len(adapter.parse(snaps)) == 4
