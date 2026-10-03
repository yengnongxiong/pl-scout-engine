"""Empirical-Bayes shrinkage toward the position-group mean (PRD §8.3).

``shrunk = (n·rate + k·prior) / (n + k)`` with ``n`` = blended minutes / 90 and ``k`` a
per-stat stabilisation constant. A player with few minutes is pulled toward the group
average; with many minutes their own rate dominates. Rankings and percentiles use shrunk
rates; displays show raw rates next to minutes.
"""

from __future__ import annotations

from scout.features.per90 import nineties


def shrink(rate: float | None, minutes: float, prior: float | None, k: float) -> float | None:
    """Shrink ``rate`` toward ``prior``; ``None`` if either is missing.

    Raises:
        ValueError: If ``k`` is not positive.
    """
    if k <= 0:
        raise ValueError("stabilisation constant k must be positive")
    if rate is None or prior is None:
        return None
    n = nineties(minutes)
    return (n * rate + k * prior) / (n + k)
