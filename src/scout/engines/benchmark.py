"""Benchmark club selection (PRD §8.8 step 2).

The benchmark is what a club is compared against: by default the top six of last
season's table, with toggles for the top four, the whole league, or a custom list. The
selected club is always excluded so it is never compared with itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import pandas as pd

from scout.errors import ConfigError

Benchmark = Literal["top6", "top4", "league", "custom"]


def benchmark_clubs(
    table: pd.DataFrame,
    benchmark: Benchmark,
    *,
    club_id: int,
    sizes: Mapping[str, int],
    custom: Sequence[int] = (),
    league_clubs: Sequence[int] = (),
) -> list[int]:
    """Team ids to compare ``club_id`` against.

    Args:
        table: Last season's standings (``team_id``, ``position``).
        benchmark: ``top6``/``top4`` (by table position), ``league`` (every current club)
            or ``custom``.
        club_id: The selected club, always excluded.
        sizes: Number of clubs per table-based benchmark (config ``benchmark_sizes``).
        custom: Team ids for ``custom``.
        league_clubs: Team ids of every club this season, for ``league``.

    Returns:
        Sorted team ids. Ties on the cut-off position are all included (``RANK``).

    Raises:
        ConfigError: If the benchmark needs data that was not given.
    """
    if benchmark == "custom":
        chosen = set(custom)
    elif benchmark == "league":
        chosen = set(league_clubs)
    else:
        size = sizes.get(benchmark)
        if size is None:
            raise ConfigError(f"no benchmark size configured for {benchmark!r}")
        if table.empty:
            raise ConfigError("no completed season to build a table-based benchmark from")
        chosen = {
            int(t) for t, p in zip(table["team_id"], table["position"], strict=True) if p <= size
        }
    chosen.discard(club_id)
    if not chosen:
        raise ConfigError(f"benchmark {benchmark!r} has no clubs after excluding the club")
    return sorted(chosen)
