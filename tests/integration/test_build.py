import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from scout import cli
from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse, seasons_in
from scout.db.models import (
    Base,
    DimMatch,
    DimPlayer,
    EntityMapReview,
    FactMarketValue,
    FactPlayerMatch,
    FactTeamMatch,
)
from scout.db.session import make_engine, make_session_factory
from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import SnapshotStore
from scout.ingest.fotmob import snapshot_name as fotmob_name
from scout.ingest.fpl import BOOTSTRAP, FIXTURES, element_summary_name
from scout.ingest.transfermarkt import club_players_name, club_search_name, market_value_name
from scout.ingest.understat import KINDS
from scout.ingest.understat import snapshot_name as us_name

FIX = PROJECT_ROOT / "tests" / "fixtures"
CONFIG = load_config(PROJECT_ROOT / "config")


def _seed(data_dir: Path, *, corrupt_xg: bool = False) -> None:
    store = SnapshotStore(data_dir / "raw", clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    store.write("fpl", BOOTSTRAP, (FIX / "fpl/synthetic_bootstrap_static.json").read_bytes())
    store.write("fpl", FIXTURES, (FIX / "fpl/synthetic_fixtures.json").read_bytes())
    for i in (11, 12):
        store.write(
            "fpl",
            element_summary_name(i),
            (FIX / f"fpl/synthetic_element_summary_{i}.json").read_bytes(),
        )
    for name in ("merged_gw", "players_raw", "teams"):
        store.write(
            "vaastav",
            f"2025-26_{name}.csv",
            (FIX / f"vaastav/synthetic_2025-26_{name}.csv").read_bytes(),
        )
    for kind in KINDS:
        body = (FIX / f"understat/synthetic_{us_name('2025-26', kind)}").read_bytes()
        if corrupt_xg and kind == "player_match":
            body = body.replace(b",0.95,0.10,", b",-0.95,0.10,")
        store.write("understat", us_name("2025-26", kind), body)
    store.write(
        "fotmob",
        fotmob_name("2025-26"),
        (FIX / f"fotmob/synthetic_{fotmob_name('2025-26')}").read_bytes(),
    )
    for name, fixture in (
        (club_search_name("Synthetic Rovers"), "club_search"),
        (club_players_name("99001"), "club_players"),
        (market_value_name("880011"), "market_value_880011"),
        (market_value_name("880013"), "market_value_880013"),
    ):
        payload = json.loads((FIX / f"transfermarkt/synthetic_{fixture}.json").read_text())
        store.write("transfermarkt", name, json.dumps(payload).encode())


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'wh.db'}")


def _count(settings: Settings, model: type[Base], **where: object) -> int:
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as session:
        stmt = select(func.count()).select_from(model)
        for col, val in where.items():
            stmt = stmt.where(getattr(model, col) == val)
        n = session.scalar(stmt) or 0
    engine.dispose()
    return n


def test_end_to_end_build_from_fixtures(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir)
    report = build_warehouse(settings, CONFIG)
    assert report.sources == ["fpl", "vaastav", "understat", "fotmob", "transfermarkt"]
    assert report.validation.ok
    assert "understat: 100.0% of FPL minutes mapped" in report.coverage
    assert _count(settings, DimPlayer) == 3
    assert _count(settings, DimMatch) == 3 + 2
    assert _count(settings, FactPlayerMatch, source="fpl") == 4
    assert _count(settings, FactPlayerMatch, source="understat") == 3
    # Last season's vaastav rows attach to the same 2025-26 match Understat created.
    assert _count(settings, FactPlayerMatch, source="vaastav") == 2
    assert _count(settings, FactTeamMatch, source="understat") == 4
    assert _count(settings, FactTeamMatch, source="fotmob") == 4
    assert _count(settings, FactMarketValue, source="transfermarkt") == 2
    assert report.review_count == _count(settings, EntityMapReview)


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    counts = [_count(settings, m) for m in (DimPlayer, DimMatch, FactPlayerMatch, FactTeamMatch)]
    build_warehouse(settings, CONFIG)
    assert [
        _count(settings, m) for m in (DimPlayer, DimMatch, FactPlayerMatch, FactTeamMatch)
    ] == counts


def test_validation_failure_stops_build(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir, corrupt_xg=True)
    with pytest.raises(DataValidationError, match="--allow-invalid"):
        build_warehouse(settings, CONFIG)
    assert not (tmp_path / "wh.db").exists()  # nothing half-written
    report = build_warehouse(settings, CONFIG, allow_invalid=True)
    assert not report.validation.ok
    assert any(i.column == "xg" for i in report.validation.issues)


def test_build_needs_fpl(tmp_path: Path) -> None:
    with pytest.raises(SourceUnavailableError, match="--source fpl"):
        build_warehouse(_settings(tmp_path), CONFIG)


def test_seasons_in_reads_name_prefixes(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    snaps = [
        store.write("understat", name, b"x")
        for name in ("2025-26_shots.csv", "2026-27_shots.csv", "fixtures.json")
    ]
    assert seasons_in(snaps) == ["2026-27", "2025-26"]


def test_cli_build_reports_validation_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir, corrupt_xg=True)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    result = CliRunner().invoke(cli.app, ["build"])
    assert result.exit_code == 1
    assert "Build stopped" in result.output
    ok = CliRunner().invoke(cli.app, ["build", "--allow-invalid"])
    assert ok.exit_code == 0, ok.output
    assert "fact_player_match:fpl: 4 rows" in ok.output
