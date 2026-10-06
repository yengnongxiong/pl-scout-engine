"""`scout demo` orchestration with every step faked (no network, no subprocesses)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from scout import cli, demo
from scout.config import Settings
from scout.db.build import BuildReport
from scout.demo import DemoSteps, plan_demo, run_demo, web_commands
from scout.errors import DataValidationError
from scout.ingest.base import SnapshotStore
from scout.ingest.fpl import BOOTSTRAP
from scout.ingest.runner import IngestResult


@pytest.mark.parametrize(
    ("snapshot", "warehouse", "refresh", "skip", "expected"),
    [
        (False, False, False, False, (True, True)),  # fresh clone: everything
        (True, True, False, False, (False, True)),  # data exists: rebuild, no ingest
        (True, True, True, False, (True, True)),  # --refresh
        (True, True, False, True, (False, False)),  # --skip-build with a warehouse
        (True, False, False, True, (False, True)),  # --skip-build but nothing built yet
        (False, True, False, True, (True, True)),  # no snapshots: ingest forces a build
    ],
)
def test_plan(
    snapshot: bool, warehouse: bool, refresh: bool, skip: bool, expected: tuple[bool, bool]
) -> None:
    plan = plan_demo(
        has_fpl_snapshot=snapshot, has_warehouse=warehouse, refresh=refresh, skip_build=skip,
        web=True,
    )  # fmt: skip
    assert (plan.ingest, plan.build) == expected
    assert plan.train == plan.build and plan.web


def test_web_commands_install_only_when_needed(tmp_path: Path) -> None:
    assert web_commands(tmp_path) == [["npm", "ci"], ["npm", "run", "dev", "--", "--strictPort"]]
    (tmp_path / "node_modules").mkdir()
    assert web_commands(tmp_path) == [["npm", "run", "dev", "--", "--strictPort"]]


def test_start_web_without_npm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(demo.shutil, "which", lambda _name: None)
    assert demo.start_web(tmp_path) is None


class FakeProcess:
    def __init__(self) -> None:
        self.stopped = False

    def terminate(self) -> None:
        self.stopped = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _steps(calls: list[str], *, fpl_ok: bool = True, build_error: bool = False) -> DemoSteps:
    process = FakeProcess()

    def ingest() -> list[IngestResult]:
        calls.append("ingest")
        return [
            IngestResult("fpl", ok=fpl_ok, error=None if fpl_ok else "blocked"),
            IngestResult("understat", ok=False, error="host_not_allowed"),
        ]

    def build() -> BuildReport:
        calls.append("build")
        if build_error:
            raise DataValidationError("fpl_player_match failed validation")
        return BuildReport()

    def start_web() -> FakeProcess:
        calls.append("web")
        return process

    return DemoSteps(
        ingest=ingest,
        build=build,
        train=lambda: calls.append("train"),
        start_web=start_web,
        serve=lambda: calls.append("serve"),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")


def test_fresh_clone_runs_every_step(tmp_path: Path) -> None:
    calls: list[str] = []
    out: list[str] = []
    assert run_demo(_settings(tmp_path), _steps(calls), echo=out.append) == 0
    assert calls == ["ingest", "build", "train", "web", "serve"]
    text = "\n".join(out)
    assert "understat                FAILED: host_not_allowed" in text
    assert "http://localhost:5173" in text


def test_existing_snapshots_skip_ingest_and_skip_build_reuses_the_warehouse(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    SnapshotStore(settings.data_dir / "raw").write("fpl", BOOTSTRAP, b"{}")
    (tmp_path / "w.db").write_bytes(b"")
    calls: list[str] = []
    assert run_demo(settings, _steps(calls), echo=lambda _s: None) == 0
    assert calls == ["build", "train", "web", "serve"]
    calls.clear()
    assert run_demo(settings, _steps(calls), skip_build=True, web=False, echo=lambda _s: None) == 0
    assert calls == ["serve"]


def test_stops_without_fpl_or_on_a_failed_build(tmp_path: Path) -> None:
    calls: list[str] = []
    out: list[str] = []
    assert run_demo(_settings(tmp_path), _steps(calls, fpl_ok=False), echo=out.append) == 1
    assert calls == ["ingest"] and "nothing to build" in out[-1]
    calls.clear()
    assert run_demo(_settings(tmp_path), _steps(calls, build_error=True), echo=out.append) == 1
    assert calls == ["ingest", "build"] and "Demo stopped" in out[-1]


def test_web_failure_still_serves_the_api(tmp_path: Path) -> None:
    calls: list[str] = []
    steps = _steps(calls)
    steps.start_web = lambda: None
    out: list[str] = []
    assert run_demo(_settings(tmp_path), steps, echo=out.append) == 0
    assert calls[-1] == "serve" and any("could not start" in line for line in out)


def test_cli_demo_wires_the_steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(settings: Settings, steps: DemoSteps, **kwargs: object) -> int:
        captured.update(kwargs, steps=steps)
        return 0

    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(demo, "run_demo", fake_run)
    result = CliRunner().invoke(cli.app, ["demo", "--skip-build", "--no-web"])
    assert result.exit_code == 0, result.output
    assert captured["skip_build"] is True and captured["web"] is False
    monkeypatch.setattr(demo, "run_demo", lambda *_a, **_k: 1)
    assert CliRunner().invoke(cli.app, ["demo"]).exit_code == 1
