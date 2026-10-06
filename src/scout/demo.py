"""``scout demo``: one command from a fresh clone to a working dashboard (CLAUDE.md, M9).

Steps, each skipped when it has nothing to do:

1. **Ingest** every source if there is no FPL snapshot yet (or ``--refresh``). A failing
   optional source (Understat, FotMob, Transfermarkt, history) is reported and the demo
   goes on with what it has; without FPL there is nothing to build, so it stops.
2. **Build** the warehouse and materialise features (validation failures stop it, rule 12).
3. **Train** the models, store their outputs and write ``docs/EVALUATION.md``.
4. **Serve**: start the Vite dev server for ``web/`` (``npm ci`` first if needed) and run the
   API in the foreground; Ctrl+C stops both.

Everything runs locally against the owner's machine; nothing is deployed.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scout.config import PROJECT_ROOT, Settings
from scout.db.build import BuildReport
from scout.errors import ScoutError
from scout.ingest.base import SnapshotStore
from scout.ingest.fpl import BOOTSTRAP
from scout.ingest.runner import IngestResult

logger = logging.getLogger(__name__)

WEB_DIR = PROJECT_ROOT / "web"
WEB_URL = "http://localhost:5173"


@dataclass(frozen=True)
class DemoPlan:
    """Which steps a demo run performs."""

    ingest: bool
    build: bool
    train: bool
    web: bool


def plan_demo(
    *,
    has_fpl_snapshot: bool,
    has_warehouse: bool,
    refresh: bool,
    skip_build: bool,
    web: bool,
) -> DemoPlan:
    """Decide the steps: ingest only without data (or on request); build unless skipped."""
    ingest = refresh or not has_fpl_snapshot
    build = ingest or not skip_build or not has_warehouse
    return DemoPlan(ingest=ingest, build=build, train=build, web=web)


class Process(Protocol):
    """The part of ``subprocess.Popen`` the demo uses."""

    def terminate(self) -> None:
        """Ask the process to stop."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the process to exit and return its code."""
        ...


def web_commands(web_dir: Path) -> list[list[str]]:
    """Commands that install (if needed) and start the web dev server."""
    install = [] if (web_dir / "node_modules").is_dir() else [["npm", "ci"]]
    return [*install, ["npm", "run", "dev", "--", "--strictPort"]]


def start_web(web_dir: Path = WEB_DIR) -> Process | None:
    """Start the Vite dev server in the background; ``None`` if npm is missing."""
    if shutil.which("npm") is None:
        logger.warning("npm not found: the API runs, but the web app needs Node.js 22+")
        return None
    *setup, serve = web_commands(web_dir)
    for command in setup:
        subprocess.run(command, cwd=web_dir, check=True)
    return subprocess.Popen(serve, cwd=web_dir)


def serve_api(host: str, port: int) -> None:  # pragma: no cover - blocks until Ctrl+C
    """Run the API in the foreground."""
    import uvicorn

    uvicorn.run("scout.api.main:app", host=host, port=port)


@dataclass
class DemoSteps:
    """The work a demo delegates (real implementations in the CLI, fakes in tests)."""

    ingest: Callable[[], Sequence[IngestResult]]
    build: Callable[[], BuildReport]
    train: Callable[[], object]
    start_web: Callable[[], Process | None]
    serve: Callable[[], None]


def run_demo(
    settings: Settings,
    steps: DemoSteps,
    *,
    refresh: bool = False,
    skip_build: bool = False,
    web: bool = True,
    echo: Callable[[str], None] = print,
) -> int:
    """Run the demo; returns a process exit code (0 = served and stopped cleanly)."""
    store = SnapshotStore(settings.data_dir / "raw")
    has_snapshot = store.latest("fpl", BOOTSTRAP) is not None
    db_url = settings.database_url
    has_warehouse = (
        not db_url.startswith("sqlite:///") or Path(db_url.removeprefix("sqlite:///")).exists()
    )
    plan = plan_demo(
        has_fpl_snapshot=has_snapshot,
        has_warehouse=has_warehouse,
        refresh=refresh,
        skip_build=skip_build,
        web=web,
    )
    try:
        if plan.ingest:
            echo("1/4 Ingesting sources (polite rate limits: this takes a while)…")
            results = steps.ingest()
            for r in results:
                echo(f"    {r.source:<24} {'ok' if r.ok else f'FAILED: {r.error}'}")
            if not any(r.source == "fpl" and r.ok for r in results):
                echo("FPL could not be ingested, so there is nothing to build.")
                return 1
        else:
            echo("1/4 Using the existing raw snapshots (pass --refresh to fetch new ones).")
        if plan.build:
            echo("2/4 Building the warehouse…")
            report = steps.build()
            echo(f"    {report.validation.summary()}")
            echo("3/4 Training models and writing docs/EVALUATION.md…")
            steps.train()
        else:
            echo("2/4 and 3/4 skipped: using the existing warehouse (--skip-build).")
    except ScoutError as exc:
        echo(f"Demo stopped: {exc.message}")
        return 1
    process = steps.start_web() if plan.web else None
    if plan.web and process is None:
        echo("    The web app could not start (is Node.js 22+ installed?). The API still runs.")
    echo(f"4/4 Serving. Dashboard: {WEB_URL}  API docs: http://127.0.0.1:8000/docs")
    try:
        steps.serve()
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        pass
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
    return 0
