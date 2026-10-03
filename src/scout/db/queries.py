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


def kpi_percentiles(engine: Engine, *, min_minutes: float) -> pd.DataFrame:
    """Position-group percentiles over the ``kpi_values`` table (``percentiles.sql``)."""
    return run_sql(engine, "percentiles", {"min_minutes": min_minutes})


def standings(engine: Engine, season_id: str) -> pd.DataFrame:
    """League table for ``season_id`` from scored matches (``standings.sql``)."""
    return run_sql(engine, "standings", {"season_id": season_id})


def club_players(engine: Engine) -> pd.DataFrame:
    """Current-season club x player minutes with position, DOB and contract."""
    frame = run_sql(engine, "club_players")
    for col in ("birth_date", "contract_expiry"):
        # SQLite returns dates as text; normalise to datetime.date (None stays None).
        frame[col] = [
            None if v is None or (isinstance(v, float) and pd.isna(v)) else pd.Timestamp(v).date()
            for v in frame[col]
        ]
    return frame


def team_matches_played(engine: Engine) -> dict[int, int]:
    """Scored current-season matches per club."""
    frame = run_sql(engine, "team_matches_played")
    return {int(t): int(n) for t, n in zip(frame["team_id"], frame["matches"], strict=True)}


def player_features(engine: Engine, season_mode: str) -> pd.DataFrame:
    """Materialised ``player_season_features`` rows for one season mode."""
    return run_sql(engine, "player_features", {"season_mode": season_mode})


def team_season_totals(engine: Engine, source: str) -> pd.DataFrame:
    """Team x season totals and per-column match counts (``team_season.sql``)."""
    return run_sql(engine, "team_season", {"source": source})
