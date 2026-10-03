from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from typer.testing import CliRunner

from scout.cli import app
from scout.config import PROJECT_ROOT, AppConfig, Settings, load_config
from scout.errors import ConfigError
from scout.ingest import runner
from scout.ingest.runner import IngestResult, club_aliases, run_ingest

FIX = PROJECT_ROOT / "tests" / "fixtures"


def _config(history_back: int = 1) -> AppConfig:
    cfg = load_config(PROJECT_ROOT / "config")
    ingest = cfg.settings.ingest.model_copy(update={"history_seasons_back": history_back})
    settings = cfg.settings.model_copy(update={"ingest": ingest})
    return cfg.model_copy(update={"settings": settings})


def _handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "fantasy.premierleague.com":
        if path.endswith("bootstrap-static/"):
            return httpx.Response(
                200, content=(FIX / "fpl/synthetic_bootstrap_static.json").read_bytes()
            )
        if path.endswith("fixtures/"):
            return httpx.Response(200, content=(FIX / "fpl/synthetic_fixtures.json").read_bytes())
        element = path.rstrip("/").split("/")[-1]
        return httpx.Response(
            200, content=(FIX / f"fpl/synthetic_element_summary_{element}.json").read_bytes()
        )
    if host == "raw.githubusercontent.com" and "Fantasy-Premier-League" in path:
        season = path.split("/data/")[1].split("/")[0]
        kind = path.rsplit("/", 1)[1]
        name = {
            "merged_gw.csv": "merged_gw",
            "players_raw.csv": "players_raw",
            "teams.csv": "teams",
        }[kind]
        file = FIX / f"vaastav/synthetic_{season}_{name}.csv"
        if not file.exists():
            return httpx.Response(404, content=b"Not Found")
        return httpx.Response(200, content=file.read_bytes())
    return httpx.Response(404, content=b"Not Found")


class FakeUnderstat:
    def _frame(self, kind: str) -> pd.DataFrame:
        return pd.read_csv(FIX / f"understat/synthetic_2025-26_{kind}.csv")

    def read_player_match_stats(self) -> pd.DataFrame:
        return self._frame("player_match")

    def read_shot_events(self) -> pd.DataFrame:
        return self._frame("shots")

    def read_team_match_stats(self) -> pd.DataFrame:
        return self._frame("team_match")


def test_fpl_then_dependent_sources(tmp_path: Path) -> None:
    results = run_ingest(
        ["understat", "vaastav", "fpl"],
        Settings(data_dir=tmp_path),
        _config(),
        transport=httpx.MockTransport(_handler),
        reader_factories={"understat": lambda season: FakeUnderstat()},
    )
    by_source = {r.source: r for r in results}
    assert [r.source for r in results] == ["fpl", "vaastav", "understat"]  # FPL first
    assert all(r.ok for r in results), results
    assert by_source["fpl"].rows == 4
    assert by_source["vaastav"].rows == 2  # 2025-26 only (history_seasons_back=1)
    assert by_source["understat"].snapshots == 6  # current + previous season, 3 kinds each
    assert by_source["fpl"].requests == 4
    assert (tmp_path / "raw" / "fpl").is_dir()


def test_dependent_source_needs_fpl_snapshot(tmp_path: Path) -> None:
    [result] = run_ingest(["vaastav"], Settings(data_dir=tmp_path), _config())
    assert not result.ok
    assert result.error is not None and "--source fpl" in result.error


def test_missing_history_season_is_reported_not_raised(tmp_path: Path) -> None:
    results = run_ingest(
        ["fpl", "vaastav"],
        Settings(data_dir=tmp_path),
        _config(history_back=2),  # 2024-25 is not in the fixtures → 404
        transport=httpx.MockTransport(_handler),
    )
    assert results[0].ok and not results[1].ok
    assert results[1].error is not None and "404" in results[1].error


def test_request_budget_applies_per_source(tmp_path: Path) -> None:
    [result] = run_ingest(
        ["fpl"],
        Settings(data_dir=tmp_path),
        _config(),
        max_requests=2,
        transport=httpx.MockTransport(_handler),
    )
    assert not result.ok and result.requests == 2
    assert result.error is not None and "budget" in result.error


def test_unknown_source_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown source"):
        run_ingest(["fbref"], Settings(data_dir=tmp_path), _config())


def test_club_aliases_maps_fpl_names() -> None:
    aliases = {"Manchester City": ["Man City", "Man. City"], "Arsenal": ["Arsenal FC"]}
    out = club_aliases(["Man City", "Synthetic Rovers"], aliases)
    assert out == {"Man City": ["Manchester City", "Man. City"], "Synthetic Rovers": []}


def test_cli_ingest_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(sources: list[str], *args: Any, **kwargs: Any) -> list[IngestResult]:
        assert sources == ["fpl"]
        return [IngestResult(source="fpl", ok=False, error="HTTP 403")]

    monkeypatch.setattr(runner, "run_ingest", fake_run)
    result = CliRunner().invoke(app, ["ingest", "--source", "fpl"])
    assert result.exit_code == 1
    assert "FAILED: HTTP 403" in result.output


def test_cli_ingest_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(sources: list[str], *args: Any, **kwargs: Any) -> list[IngestResult]:
        assert sources == ["all"]
        return [IngestResult(source="fpl", ok=True, snapshots=3, rows=10, requests=3)]

    monkeypatch.setattr(runner, "run_ingest", fake_run)
    result = CliRunner().invoke(app, ["ingest"])
    assert result.exit_code == 0, result.output
    assert "fpl" in result.output and "rows=10" in result.output
