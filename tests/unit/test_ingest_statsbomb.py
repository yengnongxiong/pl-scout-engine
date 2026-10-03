import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, SnapshotStore
from scout.ingest.statsbomb import StatsBombAdapter, events_name, matches_name

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "statsbomb"
MATCHES = (FIXTURE_DIR / "synthetic_matches_2_27.json").read_bytes()
EVENTS = (FIXTURE_DIR / "synthetic_events_3900001.json").read_bytes()


def _adapter(max_matches: int = 10) -> StatsBombAdapter:
    return StatsBombAdapter("https://sb.test/data", 2, 27, max_matches)


def test_parse_flattens_events(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    snaps = [
        store.write("statsbomb", matches_name(2, 27), MATCHES),
        store.write("statsbomb", events_name(3900001), EVENTS),
    ]
    df = _adapter().parse(snaps).set_index("event_id")
    assert len(df) == 4
    assert df.loc["e2", "type"] == "Pass"
    assert (df.loc["e2", "x"], df.loc["e2", "end_x"]) == (30.0, 62.5)
    assert df.loc["e3", "end_y"] == 30.0  # carry end location
    assert df.loc["e4", "shot_xg"] == pytest.approx(0.123)
    assert df.loc["e4", "outcome"] == "Goal"
    assert pd.isna(df.loc["e1", "player"]) and pd.isna(df.loc["e1", "x"])
    assert set(df["match_id"]) == {3900001}
    assert set(df["source"]) == {"statsbomb"}


def test_schema_changed_fails(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    events = json.loads(EVENTS)
    del events[1]["type"]
    snaps = [store.write("statsbomb", events_name(3900001), json.dumps(events).encode())]
    with pytest.raises(DataValidationError, match="schema changed"):
        _adapter().parse(snaps)


def test_bad_location_fails(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    events = json.loads(EVENTS)
    events[1]["location"] = "midfield"
    snaps = [store.write("statsbomb", events_name(3900001), json.dumps(events).encode())]
    with pytest.raises(DataValidationError, match="location"):
        _adapter().parse(snaps)


def test_fetch_caps_matches(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if "/matches/" in request.url.path:
            return httpx.Response(200, content=MATCHES)
        return httpx.Response(200, content=EVENTS)

    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    with PoliteClient(
        "statsbomb", cfg, transport=httpx.MockTransport(handler), bucket=TokenBucket(1e9, 1e9)
    ) as client:
        snaps = _adapter(max_matches=1).fetch(client, SnapshotStore(tmp_path))
    assert requested == ["/data/matches/2/27.json", "/data/events/3900001.json"]
    assert [s.name for s in snaps] == [matches_name(2, 27), events_name(3900001)]


def test_fetch_rejects_bad_match_list(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b'{"matches": "not a list", "pad": "' + b"x" * 80 + b'"}'
        )

    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    with (
        PoliteClient(
            "statsbomb", cfg, transport=httpx.MockTransport(handler), bucket=TokenBucket(1e9, 1e9)
        ) as client,
        pytest.raises(DataValidationError, match="match list"),
    ):
        _adapter().fetch(client, SnapshotStore(tmp_path))
