"""Within-position-group percentiles (PRD §8.6).

Percentiles use ``PERCENT_RANK`` semantics, ``(rank - 1) / (n - 1)`` with ties sharing the
lowest rank, scaled to 0-100, so the pandas version here matches ``percentiles.sql``.
Only players meeting the minutes threshold are ranked, and ``n_peers`` is always
returned so a percentile is never shown without its sample size (CLAUDE.md rule 8).
Inverse KPIs are ranked on the negated value so a higher percentile is always better.
"""

from __future__ import annotations

import pandas as pd

PERCENT = 100.0
KEY = ["position_group", "kpi"]


def percent_rank(values: pd.Series[float]) -> pd.Series[float]:
    """``PERCENT_RANK`` of each value within ``values`` (0-1; a single value gives 0)."""
    n = len(values)
    if n <= 1:
        return pd.Series(0.0, index=values.index)
    ranks = values.rank(method="min")
    return (ranks - 1.0) / (n - 1.0)


def percentiles(kpi_values: pd.DataFrame, *, min_minutes: float) -> pd.DataFrame:
    """Rank eligible players per position group and KPI.

    Args:
        kpi_values: Columns ``player_id, position_group, kpi, value, minutes,
            higher_is_better``.
        min_minutes: Minutes threshold for being ranked (config, PRD §8.6).

    Returns:
        Eligible rows with ``percentile`` (0-100) and ``n_peers``.
    """
    eligible = kpi_values[
        (kpi_values["minutes"] >= min_minutes)
        & kpi_values["value"].notna()
        & kpi_values["position_group"].notna()
    ].copy()
    if eligible.empty:
        return eligible.assign(percentile=pd.Series(dtype=float), n_peers=pd.Series(dtype=int))
    higher = eligible["higher_is_better"].astype(bool)
    eligible["score"] = eligible["value"].where(higher, -eligible["value"])
    eligible["percentile"] = (
        eligible.groupby(KEY, group_keys=False)["score"].apply(percent_rank) * PERCENT
    )
    eligible["n_peers"] = eligible.groupby(KEY)["score"].transform("size")
    return eligible.drop(columns=["score"])
