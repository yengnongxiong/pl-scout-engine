"""Similar players: "players like X" (PRD §8.10 step 2, US-09).

Each player is a vector of their position group's KPIs (shrunk per-90 rates, the values
rankings use, PRD §8.3), standardised across the group's ranked players (z-scores,
population standard deviation) so that every KPI is on the same scale, then multiplied
by the square root of the KPI's weight so that in the dot product each KPI counts in
proportion to its weight. Similarity is the cosine of two such vectors (-1 to 1).

Only players with a percentile on every weighted KPI take part (they met the minutes
threshold, PRD §8.6); a player missing a KPI is left out rather than given an imputed
value (CLAUDE.md rule 2). A player exactly at the group average on every KPI has no
direction and is left out too.

Search: brute force with the heap top-k by default; the k-d tree (``dsa.kdtree``) over
unit vectors gives the same ranking (``|a - b|^2 = 2 - 2 cos``) and is selectable in
config for larger pools. Complexity: brute force O(n d + n log k) per query.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from sqlalchemy import Engine

from scout.config import AppConfig
from scout.db.queries import player_features
from scout.dsa.heap_topk import top_k
from scout.dsa.kdtree import KDTree
from scout.errors import NotFoundError


@dataclass(frozen=True)
class SimilarPlayer:
    """A neighbour of the query player with its cosine similarity."""

    player_id: int
    similarity: float


@dataclass(frozen=True)
class GroupVectors:
    """Unit-length, standardised, KPI-weighted vectors for one position group."""

    kpis: tuple[str, ...]
    player_ids: tuple[int, ...]
    vectors: tuple[tuple[float, ...], ...]


def group_vectors(features: pd.DataFrame, group: str, weights: Mapping[str, float]) -> GroupVectors:
    """Build unit vectors for the ranked players of ``group``.

    Args:
        features: ``player_id, position_group, kpi, shrunk, percentile`` rows.
        group: Position group.
        weights: KPI weights for the group; zero-weight KPIs are ignored.
    """
    kpis = tuple(sorted(k for k, w in weights.items() if w > 0))
    rows = features[
        (features["position_group"] == group)
        & features["kpi"].isin(list(kpis))
        & features["percentile"].notna()
        & features["shrunk"].notna()
    ]
    values: dict[int, dict[str, float]] = {}
    for pid, kpi, shrunk in zip(rows["player_id"], rows["kpi"], rows["shrunk"], strict=True):
        values.setdefault(int(pid), {})[str(kpi)] = float(shrunk)
    complete = sorted(p for p, v in values.items() if len(v) == len(kpis))
    scales: list[tuple[float, float]] = []
    for kpi in kpis:
        column = [values[p][kpi] for p in complete]
        mean = sum(column) / len(column) if column else 0.0
        sd = math.sqrt(sum((x - mean) ** 2 for x in column) / len(column)) if column else 0.0
        scales.append((mean, sd))
    ids: list[int] = []
    vectors: list[tuple[float, ...]] = []
    for pid in complete:
        vec = [
            (values[pid][kpi] - mean) / sd * math.sqrt(weights[kpi]) if sd > 0 else 0.0
            for kpi, (mean, sd) in zip(kpis, scales, strict=True)
        ]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            continue
        ids.append(pid)
        vectors.append(tuple(x / norm for x in vec))
    return GroupVectors(kpis, tuple(ids), tuple(vectors))


def similar_players(
    vectors: GroupVectors,
    player_id: int,
    k: int,
    *,
    method: Literal["brute", "kdtree"] = "brute",
) -> list[SimilarPlayer]:
    """The ``k`` most similar players to ``player_id``, most similar first.

    Ties keep player-id order, for both methods.

    Raises:
        NotFoundError: If the player has no vector (not ranked on every KPI).
    """
    if player_id not in vectors.player_ids:
        raise NotFoundError(
            f"player {player_id} has no complete KPI profile for similarity",
            details={"player_id": player_id},
        )
    index = vectors.player_ids.index(player_id)
    query = vectors.vectors[index]
    if method == "kdtree":
        hits = KDTree(vectors.vectors).nearest(query, k + 1)
        ranked = [(i, 1.0 - d * d / 2.0) for i, d in hits if i != index][:k]
    else:
        scores = [
            (i, sum(a * b for a, b in zip(vec, query, strict=True)))
            for i, vec in enumerate(vectors.vectors)
            if i != index
        ]
        ranked = top_k(scores, k, key=lambda item: item[1])
    return [SimilarPlayer(vectors.player_ids[i], max(-1.0, min(1.0, cos))) for i, cos in ranked]


def find_similar(
    engine: Engine,
    player_id: int,
    config: AppConfig,
    *,
    k: int = 10,
    season_mode: str = "blended",
) -> list[SimilarPlayer]:
    """Similar players to ``player_id`` within their position group, from the warehouse.

    Raises:
        NotFoundError: If the player has no features or no complete KPI profile.
    """
    features = player_features(engine, season_mode)
    mine = features[features["player_id"] == player_id]
    if mine.empty:
        raise NotFoundError(f"no features for player {player_id}", details={"player_id": player_id})
    group = str(mine["position_group"].iloc[0])
    weights = {
        kpi: w
        for name, cfg in config.kpis.position_groups.items()
        if name == group
        for kpi, w in cfg.weights.items()
    }
    vectors = group_vectors(features, group, weights)
    return similar_players(vectors, player_id, k, method=config.settings.ml.similarity_method)
