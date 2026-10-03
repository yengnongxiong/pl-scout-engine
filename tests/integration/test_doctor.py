import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scout import cli
from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.doctor import run_doctor
from scout.ingest.base import SnapshotStore
from scout.ingest.fpl import BOOTSTRAP
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
FETCHED = datetime(2026, 9, 1, tzinfo=UTC)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'wh.db'}")


def test_doctor_after_build_reports_fresh_sources_and_coverage(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    report = run_doctor(settings, CONFIG, now=FETCHED + timedelta(hours=1))
    assert report.warehouse_exists
    assert report.fpl_schema.startswith("ok")
    assert {f.source for f in report.freshness} == {
        "fpl",
        "vaastav",
        "understat",
        "fotmob",
        "transfermarkt",
    }
    assert not any(f.stale for f in report.freshness)
    assert report.coverage["understat"] == pytest.approx(1.0)
    assert report.coverage["transfermarkt"] == pytest.approx(180 / 275)
    assert any("transfermarkt coverage" in w for w in report.warnings)
    assert report.last_build is not None and report.last_build["validation_ok"] is True


def test_doctor_flags_stale_sources(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    report = run_doctor(settings, CONFIG, now=FETCHED + timedelta(days=30))
    assert all(f.stale for f in report.freshness)
    assert any("fpl is stale" in w for w in report.warnings)


def test_doctor_without_warehouse(tmp_path: Path) -> None:
    report = run_doctor(_settings(tmp_path), CONFIG)
    assert not report.warehouse_exists
    assert "no FPL snapshot" in report.fpl_schema
    assert any("scout build" in w for w in report.warnings)


def test_doctor_surfaces_missing_fpl_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    boot = json.loads(
        (PROJECT_ROOT / "tests/fixtures/fpl/synthetic_bootstrap_static.json").read_text()
    )
    del boot["elements"][0]["code"]
    SnapshotStore(settings.data_dir / "raw").write("fpl", BOOTSTRAP, json.dumps(boot).encode())
    report = run_doctor(settings, CONFIG)
    assert report.fpl_schema.startswith("SCHEMA CHANGED")
    assert "elements.0.code" in report.fpl_schema
    assert any("FPL schema changed" in w for w in report.warnings)


def test_cli_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    missing = CliRunner().invoke(cli.app, ["doctor"])
    assert missing.exit_code == 1
    assert "WARNING: no warehouse yet" in missing.output
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    ok = CliRunner().invoke(cli.app, ["doctor"])
    assert ok.exit_code == 0, ok.output
    assert "understat coverage: 100.0% of FPL minutes" in ok.output
