"""Team style vectors for StyleFit (PRD §8.9).

A candidate who already plays in a side that presses, keeps the ball and attacks like
the target club should need less adapting. Each club gets a vector of style features
from ``config/kpis.yaml`` (possession share, PPDA, a directness proxy...), built as
season (or blended) rates exactly like the team KPIs, then **standardised** across this
season's clubs (z-scores, population standard deviation) so that no feature dominates
the cosine through its scale: possession lives in [0, 1] while PPDA runs to 20.

A feature a club has no data for stays ``None`` and StyleFit compares only the shared
dimensions (``engines.fit.style_fit``); a feature with fewer than two clubs, or no
spread, cannot be standardised and is ``None`` for everyone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine

from scout.config import AppConfig, StyleFeatureDef
from scout.engines.team_needs import team_kpi_values, team_totals

MIN_CLUBS_TO_STANDARDISE = 2


@dataclass(frozen=True)
class TeamStyle:
    """A club's style vector: raw rates, z-scores and the receipt behind them."""

    team_id: int
    features: tuple[str, ...]
    raw: tuple[float | None, ...]
    z: tuple[float | None, ...]
    sources: tuple[str, ...]
    as_of: str | None


def _standardise(values: Sequence[float]) -> tuple[float, float] | None:
    """Mean and population standard deviation, or ``None`` if they cannot scale."""
    if len(values) < MIN_CLUBS_TO_STANDARDISE:
        return None
    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    return (mean, std) if std > 0 else None


def style_vectors(
    totals: pd.DataFrame,
    features: Mapping[str, StyleFeatureDef],
    league_ids: Sequence[int],
    *,
    current: str,
    previous: str | None,
    lam: float,
    prev_minutes_cap: float,
) -> dict[int, TeamStyle]:
    """Standardised style vector per club in ``league_ids`` that has any style data.

    Args:
        totals: ``team_totals`` rows for the feature sources.
        features: Style feature definitions (config), in vector order.
        league_ids: This season's clubs (the standardisation population).
        current: Current season id.
        previous: Previous season to blend in, or ``None`` (current-season mode).
        lam: Blending weight λ (PRD §8.2).
        prev_minutes_cap: Cap on previous-season minutes.
    """
    names = tuple(features)
    values = team_kpi_values(
        totals,
        features,
        current=current,
        previous=previous,
        lam=lam,
        prev_minutes_cap=prev_minutes_cap,
    )
    league = set(league_ids)
    rates: dict[int, dict[str, float]] = {}
    receipts: dict[int, list[tuple[str, str | None]]] = {}
    for rec in values.to_dict(orient="records"):
        team = int(rec["team_id"])
        if team not in league:
            continue
        rates.setdefault(team, {})[str(rec["kpi"])] = float(rec["value"])
        receipts.setdefault(team, []).append((str(rec["source"]), rec["as_of"]))
    raw: dict[int, list[float | None]] = {}
    for team, rate in rates.items():
        row: list[float | None] = []
        for name in names:
            value = rate.get(name)
            divisor = features[name].divide_by
            if value is not None and divisor is not None:
                denominator = rate.get(divisor)
                value = value / denominator if denominator else None
            row.append(value)
        raw[team] = row
    scales = [
        _standardise([v for row in raw.values() if (v := row[i]) is not None])
        for i in range(len(names))
    ]
    out: dict[int, TeamStyle] = {}
    for team in sorted(raw):
        z = tuple(
            None if value is None or scale is None else (value - scale[0]) / scale[1]
            for value, scale in zip(raw[team], scales, strict=True)
        )
        stamps = [pd.Timestamp(str(a)) for _, a in receipts[team] if a is not None]
        out[team] = TeamStyle(
            team_id=team,
            features=names,
            raw=tuple(raw[team]),
            z=z,
            sources=tuple(sorted({s for s, _ in receipts[team]})),
            as_of=max(stamps).isoformat() if stamps else None,
        )
    return out


def team_styles(
    engine: Engine,
    config: AppConfig,
    league_ids: Sequence[int],
    *,
    current: str,
    previous: str | None,
) -> dict[int, TeamStyle]:
    """Style vectors for this season's clubs from the warehouse."""
    features = config.kpis.style_features
    totals = team_totals(engine, [f.source for f in features.values()])
    if totals.empty:
        return {}
    method = config.settings.methodology
    return style_vectors(
        totals,
        features,
        league_ids,
        current=current,
        previous=previous,
        lam=method.blend_lambda,
        prev_minutes_cap=method.prev_season_minutes_cap,
    )
