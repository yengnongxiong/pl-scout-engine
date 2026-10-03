"""Typer command-line interface (``scout``).

Commands are added milestone by milestone (PRD §16); M0 ships the skeleton.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from scout import __version__
from scout.config import PROJECT_ROOT, get_config, get_settings
from scout.errors import ConfigError, DataValidationError, ScoutError

DEFAULT_OPENAPI_PATH = PROJECT_ROOT / "web" / "openapi.json"

app = typer.Typer(
    name="scout",
    help="PL Scout Engine: explainable Premier League recruitment. No number without a receipt.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    """Configure logging for every command."""
    level = logging.DEBUG if verbose else get_settings().log_level
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(__version__)


@app.command("config-check")
def config_check() -> None:
    """Validate every file in config/ and report a summary."""
    try:
        cfg = get_config()
    except ConfigError as exc:
        typer.echo(f"Config invalid: {exc.message}", err=True)
        raise typer.Exit(code=1) from exc
    n_kpis = len(cfg.kpis.kpis)
    n_proxy = sum(k.is_proxy for k in cfg.kpis.kpis.values())
    typer.echo(
        f"Config OK: {n_kpis} player KPIs ({n_proxy} proxies), "
        f"{len(cfg.kpis.position_groups)} position groups, "
        f"{len(cfg.kpis.team_kpis)} team KPIs, {len(cfg.team_aliases.aliases)} clubs with aliases."
    )


@app.command()
def ingest(
    source: Annotated[
        list[str] | None,
        typer.Option("--source", "-s", help="Source to ingest (repeatable) or 'all'."),
    ] = None,
    max_requests: Annotated[
        int | None, typer.Option(help="Per-source request budget (cloud sessions use caps).")
    ] = None,
) -> None:
    """Fetch raw snapshots from live sources and validate them (owner's machine)."""
    from scout.ingest.runner import ALL_SOURCES, run_ingest

    try:
        results = run_ingest(
            source or ["all"], get_settings(), get_config(), max_requests=max_requests
        )
    except ScoutError as exc:
        typer.echo(f"Ingest failed: {exc.message}", err=True)
        raise typer.Exit(code=1) from exc
    for r in results:
        status = "ok" if r.ok else f"FAILED: {r.error}"
        extra = f" ({'; '.join(r.notes)})" if r.notes else ""
        typer.echo(
            f"{r.source:<24} {status}  snapshots={r.snapshots} rows={r.rows} "
            f"requests={r.requests}{extra}"
        )
    if not all(r.ok for r in results):
        typer.echo(f"Some sources failed. Valid sources: {', '.join(ALL_SOURCES)}", err=True)
        raise typer.Exit(code=1)


@app.command()
def build(
    allow_invalid: Annotated[
        bool,
        typer.Option("--allow-invalid", help="Load despite validation failures (logged)."),
    ] = False,
) -> None:
    """Build the warehouse from the newest raw snapshots: validate, resolve, load."""
    from scout.db.build import build_warehouse

    try:
        report = build_warehouse(get_settings(), get_config(), allow_invalid=allow_invalid)
    except DataValidationError as exc:
        typer.echo(f"Build stopped: {exc.message}", err=True)
        issues = exc.details.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                typer.echo(f"  {issue}", err=True)
        raise typer.Exit(code=1) from exc
    except ScoutError as exc:
        typer.echo(f"Build failed: {exc.message}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Sources: {', '.join(report.sources)}")
    typer.echo(report.validation.summary())
    typer.echo(report.coverage)
    for table, rows in sorted(report.written.items()):
        skipped = report.skipped.get(table, 0)
        typer.echo(f"  {table}: {rows} rows" + (f" ({skipped} skipped)" if skipped else ""))


@app.command()
def doctor() -> None:
    """Report freshness, coverage, validation status and FPL schema health."""
    from scout.db.doctor import run_doctor

    report = run_doctor(get_settings(), get_config())
    typer.echo(f"FPL schema: {report.fpl_schema}")
    if report.last_build:
        typer.echo(
            f"Last build: {report.last_build.get('built_at')} "
            f"({report.last_build.get('validation_summary')})"
        )
    for f in report.freshness:
        flag = "STALE" if f.stale else "fresh"
        typer.echo(f"  {f.source:<24} {f.last_fetched:%Y-%m-%d %H:%M} UTC  {flag}")
    for source, share in sorted(report.coverage.items()):
        typer.echo(f"  {source} coverage: {share:.1%} of FPL minutes")
    typer.echo(f"Unresolved records for review: {report.review_count}")
    for warning in report.warnings:
        typer.echo(f"WARNING: {warning}")
    if not report.warehouse_exists:
        raise typer.Exit(code=1)


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", help="Bind address (local only)."),
    port: int = typer.Option(8000, help="Port."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes."),
) -> None:
    """Serve the read-only FastAPI app (docs at /docs)."""
    import uvicorn

    uvicorn.run("scout.api.main:app", host=host, port=port, reload=reload)


@app.command("export-openapi")
def export_openapi(
    out: Annotated[Path, typer.Option(help="Output path.")] = DEFAULT_OPENAPI_PATH,
) -> None:
    """Write the OpenAPI schema used to generate the web client's types."""
    from scout.api.main import create_app

    schema = create_app().openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {out}")


if __name__ == "__main__":  # pragma: no cover
    app()
