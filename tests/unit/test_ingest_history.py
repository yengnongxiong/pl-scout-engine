from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.history import VaastavHistoryAdapter, previous_seasons, snapshot_names

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "vaastav"
FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
SEASONS = ["2025-26", "2023-24"]


def _payloads() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for season in SEASONS:
        for name in snapshot_names(season):
            out[name] = (FIXTURE_DIR / f"synthetic_{name}").read_bytes()
    return out


def _snapshots(tmp_path: Path, payloads: dict[str, bytes]) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("vaastav", name, body) for name, body in payloads.items()]


@pytest.fixture
def adapter() -> VaastavHistoryAdapter:
    return VaastavHistoryAdapter("https://archive.test/data", SEASONS)


def test_previous_seasons_counts_back_from_current() -> None:
    assert previous_seasons("2026-27", 3) == ["2025-26", "2024-25", "2023-24"]
    assert previous_seasons("2000-01", 1) == ["1999-00"]
    with pytest.raises(ValueError):
        previous_seasons("2026/27", 1)


def test_invalid_season_rejected() -> None:
    with pytest.raises(ValueError):
        VaastavHistoryAdapter("https://archive.test/", ["26-27"])


def test_parse_maps_ids_to_stable_codes(adapter: VaastavHistoryAdapter, tmp_path: Path) -> None:
    pm = adapter.parse(_snapshots(tmp_path, _payloads()))
    assert len(pm) == 3
    # The same player has different season ids (21, 31) but one stable code.
    assert set(pm.loc[pm["fpl_code"] == 500011, "season_id"]) == {"2025-26", "2023-24"}
    bo = pm[pm["fpl_code"] == 500012].iloc[0]
    assert bo["team_fpl_code_end_of_season"] == 9002
    assert bo["opponent_fpl_code"] == 9001
    assert bo["opponent_name"] == "Synthetic Rovers"
    assert bool(bo["was_home"]) is False
    assert bo["xg"] == pytest.approx(0.55)
    assert bo["tackles"] == 0  # a real recorded zero stays zero
    assert set(pm["source"]) == {"vaastav"}


def test_columns_absent_in_older_seasons_are_null_not_zero(
    adapter: VaastavHistoryAdapter, tmp_path: Path
) -> None:
    pm = adapter.parse(_snapshots(tmp_path, _payloads()))
    old = pm[pm["season_id"] == "2023-24"].iloc[0]
    for column in ("tackles", "cbi", "recoveries", "def_contribution"):
        assert old[column] is None or old[column] != old[column]  # None or NaN
    assert old["xg"] == pytest.approx(0.04)


def test_schema_changed_fails_loudly(adapter: VaastavHistoryAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    gw_name = snapshot_names("2025-26")[0]
    lines = payloads[gw_name].decode().splitlines()
    lines[0] = lines[0].replace("minutes", "mins")
    payloads[gw_name] = ("\n".join(lines) + "\n").encode()
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_unknown_element_fails(adapter: VaastavHistoryAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    players_name = snapshot_names("2025-26")[1]
    payloads[players_name] = b"id,code\n21,500011\n"
    with pytest.raises(DataValidationError, match="not in players"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_missing_season_snapshot_fails(adapter: VaastavHistoryAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    del payloads[snapshot_names("2023-24")[2]]
    with pytest.raises(DataValidationError, match="missing"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_fetch_requests_three_files_per_season(
    adapter: VaastavHistoryAdapter, tmp_path: Path
) -> None:
    payloads = _payloads()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        season = path.split("/")[2]
        gw, players, teams = snapshot_names(season)
        if path.endswith("merged_gw.csv"):
            return httpx.Response(200, content=payloads[gw])
        if path.endswith("players_raw.csv"):
            return httpx.Response(200, content=payloads[players])
        return httpx.Response(200, content=payloads[teams])

    cfg = load_config(PROJECT_ROOT / "config").settings.ingest.model_copy(
        update={"min_body_bytes": 1}
    )
    with PoliteClient(
        "vaastav", cfg, transport=httpx.MockTransport(handler), bucket=TokenBucket(1e9, 1e9)
    ) as client:
        snaps = adapter.fetch(client, SnapshotStore(tmp_path))
    assert "/data/2025-26/gws/merged_gw.csv" in requested
    assert len(snaps) == 6
    assert len(adapter.parse(snaps)) == 3
