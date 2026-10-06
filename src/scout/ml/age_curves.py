"""Delta-method aging curves and next-season projections (PRD §8.10 step 4, US-18).

How a per-90 rate typically changes from one season to the next at each age:

1. Player-seasons from the FPL history (completed past seasons only), with age at the
   season's last kickoff and per-90 rates for the configured stats.
2. **Pairs**: the same player in two consecutive seasons, both with at least
   ``min_minutes``. The change ``r(t+1) - r(t)`` is assigned to the integer age at the end of
   season ``t`` and weighted by the harmonic mean of the two seasons' minutes, so a pair is
   only as reliable as its smaller sample.
3. **Curve**: the weighted mean change per age; ages with fewer than ``min_pairs`` pairs are
   "Not available". The cumulative curve adds the changes up from the youngest age with data.

Caveat (shown wherever this is displayed): the delta method only sees players good enough to
keep playing, so declines are understated (survivorship bias), and with a few seasons of
history the curves are rough.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import Engine

from scout.config import AppConfig
from scout.db.queries import player_season_totals, season_bounds
from scout.errors import NotFoundError
from scout.ingest.history import previous_seasons
from scout.ml.value_data import blend_rates, player_context, player_seasons

HISTORY_SOURCE = "vaastav"
CURRENT_SOURCE = "fpl"
DAYS_PER_YEAR = 365.25
MIN_SEASONS = 2  # a pair needs two consecutive seasons
CAVEAT = (
    "Delta-method age curves only see players good enough to keep playing, so declines are "
    "understated (survivorship bias); with a few seasons of history they are rough guides."
)


@dataclass(frozen=True)
class AgePoint:
    """Typical next-season change at one age."""

    age: int
    delta: float | None
    cumulative: float | None
    n_pairs: int


@dataclass(frozen=True)
class AgeCurve:
    """One stat's aging curve."""

    metric: str
    label: str
    points: list[AgePoint]
    n_pairs: int

    def at(self, age: int) -> AgePoint | None:
        """The point for ``age`` (``None`` outside the curve's range)."""
        return next((p for p in self.points if p.age == age), None)


@dataclass
class AgeCurves:
    """All curves plus the data window they were built from."""

    curves: list[AgeCurve]
    seasons: list[str]
    min_minutes: float
    min_pairs: int
    history_as_of: str | None = None
    caveat: str = CAVEAT
    pair_count: int = field(default=0)


def harmonic_mean(a: float, b: float) -> float:
    """``2ab / (a + b)`` (0 when both are 0)."""
    return 2 * a * b / (a + b) if a + b > 0 else 0.0


def delta_pairs(rows: pd.DataFrame, metrics: Sequence[str], *, min_minutes: float) -> pd.DataFrame:
    """Consecutive-season changes per player and stat.

    Args:
        rows: ``player_id, season_id, age, minutes`` plus ``<metric>_p90`` columns.
        metrics: Stat names (``<metric>_p90`` columns).
        min_minutes: Minutes both seasons of a pair need.

    Returns:
        ``player_id, season_from, season_to, age, metric, delta, weight``.
    """
    by_key = {(int(r["player_id"]), str(r["season_id"])): r for r in rows.to_dict(orient="records")}
    out: list[dict[str, object]] = []
    for (pid, season), later in sorted(by_key.items()):
        earlier = by_key.get((pid, previous_seasons(season, 1)[0]))
        if earlier is None:
            continue
        m0, m1 = float(earlier["minutes"] or 0.0), float(later["minutes"] or 0.0)
        age = earlier.get("age")
        if m0 < min_minutes or m1 < min_minutes or age is None or pd.isna(age):
            continue
        for metric in metrics:
            r0, r1 = earlier.get(f"{metric}_p90"), later.get(f"{metric}_p90")
            if r0 is None or r1 is None or pd.isna(r0) or pd.isna(r1):
                continue
            out.append(
                {
                    "player_id": pid,
                    "season_from": str(earlier["season_id"]),
                    "season_to": season,
                    "age": math.floor(float(age)),
                    "metric": metric,
                    "delta": float(r1) - float(r0),
                    "weight": harmonic_mean(m0, m1),
                }
            )
    columns = ["player_id", "season_from", "season_to", "age", "metric", "delta", "weight"]
    return pd.DataFrame(out, columns=columns)


def age_curve(
    pairs: pd.DataFrame,
    metric: str,
    label: str,
    *,
    min_pairs: int,
    age_min: int,
    age_max: int,
) -> AgeCurve:
    """Weighted mean change per age and the cumulative curve for one stat."""
    mine = pairs[pairs["metric"] == metric]
    points: list[AgePoint] = []
    running: float | None = None
    for age in range(age_min, age_max + 1):
        at_age = mine[mine["age"] == age]
        n = len(at_age)
        weight = float(at_age["weight"].sum()) if n else 0.0
        delta = (
            float((at_age["delta"] * at_age["weight"]).sum()) / weight
            if n >= min_pairs and weight > 0
            else None
        )
        if delta is not None and running is None:
            running = 0.0  # the curve starts at the youngest age with enough data
        cumulative = running
        if running is not None:
            running = running + delta if delta is not None else None
        points.append(AgePoint(age=age, delta=delta, cumulative=cumulative, n_pairs=n))
    return AgeCurve(metric=metric, label=label, points=points, n_pairs=len(mine))


def build_curves(engine: Engine, config: AppConfig) -> AgeCurves:
    """Age curves from the completed past seasons in the warehouse.

    Raises:
        NotFoundError: If there are fewer than two past seasons of FPL history.
    """
    cfg = config.settings.age_curves
    current, players = player_context(engine)
    totals = player_season_totals(engine)
    history = totals[(totals["source"] == HISTORY_SOURCE) & (totals["season_id"] != current)]
    seasons = sorted({str(s) for s in history["season_id"]})
    if len(seasons) < MIN_SEASONS:
        raise NotFoundError(
            "age curves need two past seasons of FPL history; run `scout ingest --source vaastav`",
            details={"seasons": seasons},
        )
    bounds = season_bounds(engine)
    ends = {
        str(s): pd.Timestamp(last).date()
        for s, last in zip(bounds["season_id"], bounds["last_kickoff"], strict=True)
    }
    metrics = list(cfg.metrics)
    rows = player_seasons(
        totals, players, ends, {}, source=HISTORY_SOURCE, seasons=seasons, per90_stats=metrics
    )
    pairs = delta_pairs(rows, metrics, min_minutes=cfg.min_minutes)
    curves = [
        age_curve(
            pairs,
            metric,
            label,
            min_pairs=cfg.min_pairs,
            age_min=cfg.age_min,
            age_max=cfg.age_max,
        )
        for metric, label in cfg.metrics.items()
    ]
    known = history["fetched_at"].dropna()
    return AgeCurves(
        curves=curves,
        seasons=seasons,
        min_minutes=cfg.min_minutes,
        min_pairs=cfg.min_pairs,
        history_as_of=str(known.max()) if not known.empty else None,
        pair_count=len(pairs),
    )


@dataclass(frozen=True)
class Projection:
    """A player's blended rate, the typical change at their age and the projection."""

    metric: str
    label: str
    current: float | None
    delta: float | None
    projected: float | None
    n_pairs: int


@dataclass
class PlayerProjection:
    """Next-season projections for one player."""

    player_id: int
    age: int | None
    projections: list[Projection]
    effective_minutes: float | None


def project_player(
    engine: Engine,
    player_id: int,
    config: AppConfig,
    curves: AgeCurves,
    *,
    as_of: date | None = None,
) -> PlayerProjection:
    """Apply the age curves to a player's blended FPL rates (this season + last).

    Raises:
        NotFoundError: If the player has no FPL minutes this season or last.
    """
    today = as_of or date.today()
    current, players = player_context(engine)
    previous = previous_seasons(current, 1)[0]
    metrics = list(config.settings.age_curves.metrics)
    totals = player_season_totals(engine)
    mine = totals[totals["player_id"] == player_id]

    def rows(season: str, source: str) -> pd.DataFrame:
        return player_seasons(
            mine, players, {}, {}, source=source, seasons=[season], per90_stats=metrics
        )

    cur, prev = rows(current, CURRENT_SOURCE), rows(previous, HISTORY_SOURCE)
    if cur.empty and prev.empty:
        raise NotFoundError(
            f"player {player_id} has no FPL minutes this season or last",
            details={"player_id": player_id},
        )
    rates = prev if cur.empty else blend_rates(cur, prev, metrics, config.settings.methodology)
    rec = rates.to_dict(orient="records")[0]
    birth = players.get(player_id, (None, None))[1]
    age = math.floor((today - birth).days / DAYS_PER_YEAR) if birth is not None else None
    out: list[Projection] = []
    for curve in curves.curves:
        rate = _number(rec.get(f"{curve.metric}_p90"))
        point = curve.at(age) if age is not None else None
        delta = point.delta if point else None
        out.append(
            Projection(
                metric=curve.metric,
                label=curve.label,
                current=rate,
                delta=delta,
                projected=max(0.0, rate + delta)
                if rate is not None and delta is not None
                else None,
                n_pairs=point.n_pairs if point else 0,
            )
        )
    return PlayerProjection(
        player_id=player_id,
        age=age,
        projections=out,
        effective_minutes=_number(rec.get("effective_minutes", rec.get("minutes"))),
    )


def _number(value: object) -> float | None:
    """A float, or ``None`` for a missing value (never 0, CLAUDE.md rule 2)."""
    if value is None:
        return None
    number = float(str(value))
    return None if math.isnan(number) else number
