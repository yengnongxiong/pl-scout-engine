"""Position groups from Understat formation slots (PRD §8.5 fallback).

Transfermarkt's detailed position is the primary source of a player's position group. When
a player has no Transfermarkt record (a new arrival missing from the stale datasets export,
say), the coarse FPL type would put every defender with the centre-backs and every
midfielder in central midfield. Understat records the formation slot a player started in
for every match; the group with the most minutes across those slots is a far better
fallback.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from scout.config import PositionGroup


def understat_position_groups(
    player_match: pd.DataFrame, slot_groups: Mapping[str, PositionGroup]
) -> dict[int, PositionGroup]:
    """Each Understat player's position group by minutes played in each slot.

    Args:
        player_match: Understat player-match rows (``understat_player_id``, ``position``,
            ``minutes``).
        slot_groups: Understat slot (``"DC"``, ``"AMR"`` …) → position group, from
            ``config/positions.yaml``. Slots not listed ("Sub") are ignored.

    Returns:
        ``understat_player_id → position group``; players with no listed slot are left out.
        Ties go to the alphabetically first group so builds are reproducible.
    """
    minutes: dict[int, dict[PositionGroup, float]] = {}
    for rec in player_match.to_dict(orient="records"):
        slot, played = rec.get("position"), rec.get("minutes")
        if not isinstance(slot, str) or slot not in slot_groups:
            continue
        if played is None or (isinstance(played, float) and math.isnan(played)):
            continue
        if float(played) <= 0:
            continue
        by_group = minutes.setdefault(int(rec["understat_player_id"]), {})
        group = slot_groups[slot]
        by_group[group] = by_group.get(group, 0.0) + float(played)
    return {
        pid: min(groups.items(), key=lambda item: (-item[1], item[0]))[0]
        for pid, groups in minutes.items()
    }
