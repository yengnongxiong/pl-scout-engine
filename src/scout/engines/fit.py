"""FitScore: how well a candidate fills a club's need (PRD §8.9).

``FitScore (0-100) = Σ weight_c x component_c`` over five components, each scored 0-100:

- **NeedFill**: the candidate's percentiles on the KPIs where the club trails the
  benchmark, weighted by KPI weight x gap, so the biggest shortfalls count most.
- **RoleQuality**: the overall position-weighted percentile.
- **Reliability**: minutes volume blended with current availability (FPL status).
- **StyleFit**: cosine similarity of the candidate's team style vector with the target
  club's, mapped from [-1, 1] to [0, 100].
- **AgeProfile**: 100 inside the group's peak-age window, losing points per year outside.

A component without evidence (unknown age or status, no team style data) is left out and
the remaining weights are renormalised, so missing data narrows the evidence instead of
scoring 0 (CLAUDE.md rule 2); the breakdown records the weights actually used.

The upgrade gate compares NeedFill with the incumbent's: a candidate must beat the club's
minutes leader in the group by ``upgrade_gate_min_delta`` points to count as an upgrade.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from scout.config import ReliabilityConfig

MAX_SCORE = 100.0
MIN_STYLE_DIMENSIONS = 2

GateResult = Literal["upgrade", "sideways", "no_incumbent", "insufficient_data"]


@dataclass(frozen=True)
class FitBreakdown:
    """A FitScore with its components and the renormalised weights applied."""

    total: float | None
    components: dict[str, float | None]
    weights_used: dict[str, float]


def weighted_percentile(
    percentiles: Mapping[str, float | None], weights: Mapping[str, float]
) -> float | None:
    """Weighted mean percentile over the KPIs with a percentile and positive weight.

    Weights are renormalised over the KPIs that have evidence; ``None`` when none do.
    """
    total = wsum = 0.0
    for kpi, weight in weights.items():
        pct = percentiles.get(kpi)
        if pct is None or math.isnan(pct) or weight <= 0:
            continue
        total += weight * pct
        wsum += weight
    return total / wsum if wsum > 0 else None


def deficit_weights(gaps: Mapping[str, tuple[float, float | None]]) -> dict[str, float]:
    """NeedFill weights: KPI weight x gap for each KPI where the club trails.

    Args:
        gaps: ``kpi -> (group KPI weight, gap)`` where gap = benchmark - club (or ``None``).
    """
    return {
        kpi: weight * gap
        for kpi, (weight, gap) in gaps.items()
        if gap is not None and gap > 0 and weight > 0
    }


def need_fill(
    percentiles: Mapping[str, float | None],
    deficits: Mapping[str, float],
    group_weights: Mapping[str, float],
) -> float | None:
    """Candidate's weighted percentile on the deficient KPIs.

    When the club trails on nothing in this group, the need is general quality, so the
    group weights are used (NeedFill equals RoleQuality).
    """
    return weighted_percentile(percentiles, deficits or group_weights)


def reliability(
    effective_minutes: float | None,
    status: str | None,
    chance_of_playing: float | None,
    cfg: ReliabilityConfig,
) -> float | None:
    """Minutes volume and current availability, 0-100.

    Volume = min(1, minutes / ``full_minutes``). Availability = FPL's chance of playing
    when given, else the configured value for the status code; an unknown status is
    missing, not unavailable.
    """
    parts: list[tuple[float, float]] = []
    if effective_minutes is not None and not math.isnan(effective_minutes):
        volume = min(1.0, max(effective_minutes, 0.0) / cfg.full_minutes)
        parts.append((cfg.volume_weight, volume))
    if chance_of_playing is not None and not math.isnan(chance_of_playing):
        parts.append((cfg.availability_weight, min(max(chance_of_playing, 0.0), 100.0) / 100))
    elif status is not None and status in cfg.status_availability:
        parts.append((cfg.availability_weight, cfg.status_availability[status]))
    wsum = sum(w for w, _ in parts)
    if wsum <= 0:
        return None
    return MAX_SCORE * sum(w * v for w, v in parts) / wsum


def style_fit(candidate: Sequence[float | None], club: Sequence[float | None]) -> float | None:
    """Cosine similarity of two (standardised) team style vectors, mapped to 0-100.

    Only dimensions known for both teams are compared; fewer than two shared dimensions
    or a zero vector gives ``None`` (a cosine over one dimension is just a sign).
    """
    pairs = [
        (a, b)
        for a, b in zip(candidate, club, strict=True)
        if a is not None and b is not None and not math.isnan(a) and not math.isnan(b)
    ]
    if len(pairs) < MIN_STYLE_DIMENSIONS:
        return None
    dot = sum(a * b for a, b in pairs)
    norm_a = math.sqrt(sum(a * a for a, _ in pairs))
    norm_b = math.sqrt(sum(b * b for _, b in pairs))
    if norm_a == 0 or norm_b == 0:
        return None
    cosine = max(-1.0, min(1.0, dot / (norm_a * norm_b)))
    return MAX_SCORE * (1.0 + cosine) / 2.0


def age_profile(
    age: float | None, window: tuple[int, int], penalty_per_year: float
) -> float | None:
    """100 inside the peak-age window, minus ``penalty_per_year`` per year outside it."""
    if age is None or math.isnan(age):
        return None
    low, high = window
    distance = max(low - age, age - high, 0.0)
    return max(0.0, MAX_SCORE - penalty_per_year * distance)


def fit_score(components: Mapping[str, float | None], weights: Mapping[str, float]) -> FitBreakdown:
    """Weighted FitScore over the components with evidence (weights renormalised)."""
    used = {
        name: weight
        for name, weight in weights.items()
        if weight > 0 and components.get(name) is not None
    }
    wsum = sum(used.values())
    if wsum <= 0:
        return FitBreakdown(None, dict(components), {})
    total = sum(w * float(components[name] or 0.0) for name, w in used.items()) / wsum
    return FitBreakdown(total, dict(components), {n: w / wsum for n, w in used.items()})


def upgrade_gate(
    candidate_need_fill: float | None, incumbent_need_fill: float | None, min_delta: float
) -> GateResult:
    """Does the candidate beat the incumbent on NeedFill by ``min_delta`` points?"""
    if candidate_need_fill is None:
        return "insufficient_data"
    if incumbent_need_fill is None:
        return "no_incumbent"
    if candidate_need_fill - incumbent_need_fill >= min_delta:
        return "upgrade"
    return "sideways"
