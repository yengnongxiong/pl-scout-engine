"""Typer command-line interface (``scout``).

Commands are added milestone by milestone (PRD §16); M0 ships the skeleton.
"""

from __future__ import annotations

import logging

import typer

from scout import __version__
from scout.config import get_config, get_settings
from scout.errors import ConfigError

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


if __name__ == "__main__":  # pragma: no cover
    app()
