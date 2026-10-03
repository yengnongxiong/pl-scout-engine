"""Season blending for early-season stability (PRD §8.2).

``blended = (m_cur·r_cur + λ·m_prev·r_prev) / (m_cur + λ·m_prev)``, with previous-season
minutes capped. It is a minutes-weighted average where last season's minutes count for
λ of this season's: early on, last season dominates; by mid-season, this season does.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Blended:
    """A blended rate and the effective minutes behind it."""

    rate: float | None
    minutes: float
    used_previous: bool


def blend(
    rate_cur: float | None,
    minutes_cur: float,
    rate_prev: float | None,
    minutes_prev: float,
    *,
    lam: float,
    prev_minutes_cap: float,
) -> Blended:
    """Blend this season's rate with last season's.

    Args:
        rate_cur: Current-season per-90 rate (``None`` if not available).
        minutes_cur: Current-season minutes.
        rate_prev: Previous-season per-90 rate (``None`` if not available).
        minutes_prev: Previous-season minutes (capped at ``prev_minutes_cap``).
        lam: Weight λ on previous-season minutes (config ``blend_lambda``).
        prev_minutes_cap: Cap on previous-season minutes (config).

    Returns:
        The blended rate and effective minutes ``m_cur + λ·min(m_prev, cap)``. When only
        one season has a rate, that season's rate and minutes are used alone.
    """
    m_cur = max(minutes_cur, 0.0) if rate_cur is not None else 0.0
    m_prev = min(max(minutes_prev, 0.0), prev_minutes_cap) if rate_prev is not None else 0.0
    weight_prev = lam * m_prev
    total = m_cur + weight_prev
    if total <= 0:
        return Blended(None, 0.0, False)
    numerator = (m_cur * rate_cur if rate_cur is not None else 0.0) + (
        weight_prev * rate_prev if rate_prev is not None else 0.0
    )
    return Blended(numerator / total, total, weight_prev > 0)
