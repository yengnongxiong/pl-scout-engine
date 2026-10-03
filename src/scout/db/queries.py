"""Run the analytical SQL files in ``db/sql`` and return DataFrames."""

from __future__ import annotations

from importlib import resources

import pandas as pd
from sqlalchemy import Engine, text

from scout.errors import ConfigError


def load_sql(name: str) -> str:
    """Read ``db/sql/<name>.sql`` from the installed package."""
    try:
        return resources.files("scout.db.sql").joinpath(f"{name}.sql").read_text("utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"no SQL file named {name}.sql") from exc


def run_sql(engine: Engine, name: str, params: dict[str, object] | None = None) -> pd.DataFrame:
    """Execute a named SQL file and return its rows as a DataFrame."""
    with engine.connect() as conn:
        result = conn.execute(text(load_sql(name)), params or {})
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def player_season_totals(engine: Engine) -> pd.DataFrame:
    """Per player x season x club x source totals (``player_season.sql``)."""
    return run_sql(engine, "player_season")


def defensive_padj_totals(
    engine: Engine, *, even_share: float, clip_min: float, clip_max: float
) -> pd.DataFrame:
    """Possession-adjusted tackles, recoveries and CBI (``defensive_padj.sql``)."""
    params: dict[str, object] = {
        "even_share": even_share,
        "clip_min": clip_min,
        "clip_max": clip_max,
    }
    return run_sql(engine, "defensive_padj", params)
