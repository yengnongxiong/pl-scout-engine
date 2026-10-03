"""Possession adjustment for defensive volume stats (PRD §8.4).

A team that has the ball less has more chances to tackle and intercept, inflating raw
defensive counts. Each match is scaled by ``0.5 / opponent_possession_share`` (an even
match is unchanged), with the multiplier clipped to a configured range so extreme
possession can't dominate. Matches without possession stay unadjusted and are flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

EVEN_SHARE = 0.5


def possession_multiplier(
    opp_possession_share: float | None, *, clip_min: float, clip_max: float
) -> float | None:
    """``0.5 / opp_share`` clipped to ``[clip_min, clip_max]``; ``None`` if unknown."""
    if opp_possession_share is None or opp_possession_share <= 0:
        return None
    return min(max(EVEN_SHARE / opp_possession_share, clip_min), clip_max)


@dataclass(frozen=True)
class AdjustedTotal:
    """A possession-adjusted season total and how many matches lacked possession."""

    total: float
    matches: int
    unadjusted_matches: int

    @property
    def fully_adjusted(self) -> bool:
        """Whether every match had possession data."""
        return self.unadjusted_matches == 0


def adjust_matches(
    values: list[tuple[float, float | None]], *, clip_min: float, clip_max: float
) -> AdjustedTotal:
    """Sum per-match ``(raw_value, opp_possession_share)`` after adjustment.

    Matches with unknown possession contribute their raw value and are counted as
    unadjusted, so the KPI can be flagged "unadjusted" (CLAUDE.md rule 9).
    """
    total, missing = 0.0, 0
    for raw, opp_share in values:
        mult = possession_multiplier(opp_share, clip_min=clip_min, clip_max=clip_max)
        if mult is None:
            missing += 1
            total += raw
        else:
            total += raw * mult
    return AdjustedTotal(total, len(values), missing)
