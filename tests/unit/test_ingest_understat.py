from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.understat import KINDS, UnderstatAdapter, snapshot_name, soccerdata_season

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "understat"
FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
SEASON = "2025-26"


def _payloads() -> dict[str, bytes]:
    return {
        snapshot_name(SEASON, kind): (
            FIXTURE_DIR / f"synthetic_{snapshot_name(SEASON, kind)}"
        ).read_bytes()
        for kind in KINDS
    }


def _snapshots(tmp_path: Path, payloads: dict[str, bytes]) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("understat", name, body) for name, body in payloads.items()]


@pytest.fixture
def adapter() -> UnderstatAdapter:
    return UnderstatAdapter([SEASON])


def test_soccerdata_season_code() -> None:
    assert soccerdata_season("2025-26") == "2526"
    assert soccerdata_season("1999-00") == "9900"
    with pytest.raises(ValueError):
        soccerdata_season("2025")


def test_npxg_excludes_penalty_xg(adapter: UnderstatAdapter, tmp_path: Path) -> None:
    pm = adapter.parse(_snapshots(tmp_path, _payloads()))
    assert len(pm) == 3
    bo = pm[(pm["understat_player_id"] == 8802) & (pm["understat_game_id"] == 9101)].iloc[0]
    # Hand calc: xG 0.95 - penalty xG 0.76 = 0.19.
    assert bo["npxg"] == pytest.approx(0.19)
    assert bo["xg_buildup"] == pytest.approx(0.05)
    alex = pm[pm["understat_player_id"] == 8801].iloc[0]
    assert alex["npxg"] == pytest.approx(0.05)  # corner header is not a penalty
    assert alex["key_passes"] == 2
    assert alex["yellow_cards"] == 1
    assert set(pm["source"]) == {"understat"}
    assert (pm["fetched_at"] == FETCHED_AT).all()


def test_team_match_splits_and_ppda(adapter: UnderstatAdapter, tmp_path: Path) -> None:
    tm = adapter.parse_team_match(_snapshots(tmp_path, _payloads()))
    assert len(tm) == 4
    home = tm[(tm["understat_game_id"] == 9101) & tm["is_home"]].iloc[0]
    assert home["team_name"] == "Synthetic Rovers"
    assert home["ppda"] == pytest.approx(8.5)
    assert home["ppda_allowed"] == pytest.approx(12.25)
    assert home["deep"] == 7
    assert home["deep_allowed"] == 3
    assert home["xga"] == pytest.approx(0.95)
    assert home["npxga"] == pytest.approx(0.19)
    assert home["set_piece_xg"] == pytest.approx(0.05)
    assert home["set_piece_xga"] == pytest.approx(0.07)
    assert home["open_play_xga"] == pytest.approx(0.12)
    away = tm[(tm["understat_game_id"] == 9101) & ~tm["is_home"]].iloc[0]
    assert away["set_piece_xg"] == pytest.approx(0.07)
    assert away["open_play_xga"] == pytest.approx(0.40)


def test_missing_values_stay_null(adapter: UnderstatAdapter, tmp_path: Path) -> None:
    tm = adapter.parse_team_match(_snapshots(tmp_path, _payloads()))
    away = tm[(tm["understat_game_id"] == 9102) & ~tm["is_home"]].iloc[0]
    home = tm[(tm["understat_game_id"] == 9102) & tm["is_home"]].iloc[0]
    assert pd.isna(away["xg"]) and pd.isna(home["xga"])
    assert pd.isna(away["ppda"]) and pd.isna(home["ppda_allowed"])
    # No shot events for the game → unknown, not 0.
    assert pd.isna(home["set_piece_xg"]) and pd.isna(home["open_play_xga"])
    assert home["deep"] == 2


def test_schema_changed_fails_loudly(adapter: UnderstatAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    name = snapshot_name(SEASON, "player_match")
    payloads[name] = payloads[name].replace(b"xg_buildup", b"xgBuildup", 1)
    with pytest.raises(DataValidationError, match="schema changed"):
        adapter.parse(_snapshots(tmp_path, payloads))


def test_missing_shots_snapshot_fails(adapter: UnderstatAdapter, tmp_path: Path) -> None:
    payloads = _payloads()
    del payloads[snapshot_name(SEASON, "shots")]
    with pytest.raises(DataValidationError, match="missing"):
        adapter.parse(_snapshots(tmp_path, payloads))


class FakeReader:
    def __init__(self, empty_kind: str | None = None) -> None:
        self.empty_kind = empty_kind

    def _frame(self, kind: str) -> pd.DataFrame:
        if kind == self.empty_kind:
            return pd.DataFrame()
        frame = pd.read_csv(FIXTURE_DIR / f"synthetic_{snapshot_name(SEASON, kind)}")
        return frame.set_index(["league", "season", "game"])

    def read_player_match_stats(self) -> pd.DataFrame:
        return self._frame("player_match")

    def read_shot_events(self) -> pd.DataFrame:
        return self._frame("shots")

    def read_team_match_stats(self) -> pd.DataFrame:
        return self._frame("team_match")


def _client(max_requests: int | None = None) -> PoliteClient:
    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    return PoliteClient("understat", cfg, bucket=TokenBucket(1e9, 1e9), max_requests=max_requests)


def test_fetch_round_trips_through_snapshots(tmp_path: Path) -> None:
    seasons_seen: list[str] = []

    def factory(season: str) -> object:
        seasons_seen.append(season)
        return FakeReader()

    adapter = UnderstatAdapter([SEASON], reader_factory=factory)
    with _client() as client:
        snaps = adapter.fetch(client, SnapshotStore(tmp_path))
        assert client.requests_made == 3
    assert seasons_seen == [SEASON]
    assert len(adapter.parse(snaps)) == 3
    assert len(adapter.parse_team_match(snaps)) == 4


def test_fetch_empty_frame_is_a_failure(tmp_path: Path) -> None:
    adapter = UnderstatAdapter([SEASON], reader_factory=lambda s: FakeReader("shots"))
    with _client() as client, pytest.raises(SourceUnavailableError, match="no shots"):
        adapter.fetch(client, SnapshotStore(tmp_path))


def test_fetch_respects_request_budget(tmp_path: Path) -> None:
    adapter = UnderstatAdapter([SEASON], reader_factory=lambda s: FakeReader())
    with _client(max_requests=2) as client, pytest.raises(SourceUnavailableError, match="budget"):
        adapter.fetch(client, SnapshotStore(tmp_path))
