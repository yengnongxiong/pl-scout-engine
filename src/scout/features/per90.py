"""Per-90 normalisation (PRD §8.1).

Counting stats are converted to rates per 90 minutes, never per match: double gameweeks
and substitute appearances make per-match rates misleading (CLAUDE.md rule 8).
"""

from __future__ import annotations

MINUTES_PER_MATCH = 90.0


def per90(total: float | None, minutes: float | None) -> float | None:
    """Rate per 90 minutes; ``None`` when the total is missing or no minutes were played.

    Zero minutes gives ``None`` (no information), never 0 (CLAUDE.md rule 2).
    """
    if total is None or minutes is None or minutes <= 0:
        return None
    return total * MINUTES_PER_MATCH / minutes


def nineties(minutes: float) -> float:
    """Minutes expressed as full matches (``n`` in the shrinkage formula, PRD §8.3)."""
    return max(minutes, 0.0) / MINUTES_PER_MATCH
