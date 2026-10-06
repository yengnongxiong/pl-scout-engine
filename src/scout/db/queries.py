"""Run the analytical SQL files in ``db/sql`` and return DataFrames."""

from __future__ import annotations

import math
from datetime import date, datetime
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


# Receipt timestamps: SQLite returns them as text, Postgres as tz-aware datetimes.
TIMESTAMP_COLUMNS = frozenset({"fetched_at", "as_of", "status_as_of"})


def iso_timestamp(value: object) -> str | None:
    """A stored timestamp as ISO 8601 in UTC; ``None`` when missing (never "NaT")."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    stamp = pd.Timestamp(value) if isinstance(value, (datetime, date)) else pd.Timestamp(str(value))
    if not isinstance(stamp, pd.Timestamp):  # NaT
        return None
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.isoformat()


def run_sql(engine: Engine, name: str, params: dict[str, object] | None = None) -> pd.DataFrame:
    """Execute a named SQL file and return its rows as a DataFrame.

    Receipt timestamp columns come back as ISO 8601 UTC strings on every backend, so a
    receipt reads the same whether the warehouse is SQLite or Postgres.
    """
    with engine.connect() as conn:
        result = conn.execute(text(load_sql(name)), params or {})
        columns = list(result.keys())
        rows = result.fetchall()
    frame = pd.DataFrame(rows, columns=columns)
    for column in TIMESTAMP_COLUMNS.intersection(columns):
        frame[column] = pd.Series(
            [iso_timestamp(v) for v in frame[column]], index=frame.index, dtype=object
        )
    return frame


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
    return _as_dates(run_sql(engine, "club_players"), ("birth_date", "contract_expiry"))


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


def _as_dates(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """SQLite returns dates as text; normalise to ``datetime.date`` (None stays None)."""
    for col in columns:
        frame[col] = [
            None if v is None or (isinstance(v, float) and pd.isna(v)) else pd.Timestamp(v).date()
            for v in frame[col]
        ]
    return frame


def player_profiles(engine: Engine) -> pd.DataFrame:
    """Current club, position, DOB and newest FPL availability (``player_profiles.sql``)."""
    return _as_dates(run_sql(engine, "player_profiles"), ("birth_date", "contract_expiry"))


def latest_market_values(engine: Engine) -> pd.DataFrame:
    """Newest Transfermarkt estimated market value per player and source."""
    return _as_dates(run_sql(engine, "market_values"), ("tm_last_updated",))


def market_value_history(engine: Engine) -> pd.DataFrame:
    """Every stored valuation with its Transfermarkt as-of date, all sources."""
    return _as_dates(run_sql(engine, "market_value_history"), ("tm_last_updated",))


def season_bounds(engine: Engine) -> pd.DataFrame:
    """First and last kickoff (UTC timestamps) and match count per season."""
    frame = run_sql(engine, "season_bounds")
    for col in ("first_kickoff", "last_kickoff"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    return frame
