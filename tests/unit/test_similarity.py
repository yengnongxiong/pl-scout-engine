"""Similar-player search (PRD §8.10 step 2), hand-checked and brute force vs k-d tree."""

import math
import random

import pandas as pd
import pytest

from scout.errors import NotFoundError
from scout.ml.similarity import group_vectors, similar_players


def features(
    rows: list[tuple[int, str, float | None, float | None]], group: str = "X"
) -> pd.DataFrame:
    return pd.DataFrame(
        [(pid, group, kpi, shrunk, pct) for pid, kpi, shrunk, pct in rows],
        columns=["player_id", "position_group", "kpi", "shrunk", "percentile"],
    )


@pytest.fixture
def square() -> pd.DataFrame:
    # (a, b) per player: deviations from the mean (2, 2) are (-1,-1), (0,0), (1,1), (1,-1), (-1,1).
    points = {1: (1, 1), 2: (2, 2), 3: (3, 3), 4: (3, 1), 5: (1, 3)}
    rows = [
        (p, kpi, float(v), 50.0) for p, (a, b) in points.items() for kpi, v in (("a", a), ("b", b))
    ]
    rows += [(6, "a", 9.0, 50.0)]  # missing KPI b: no vector, nothing imputed
    rows += [(7, "a", 9.0, None), (7, "b", 9.0, None)]  # below the minutes threshold
    return features(rows)


def test_vectors_are_standardised_unit_and_complete(square: pd.DataFrame) -> None:
    vecs = group_vectors(square, "X", {"a": 1.0, "b": 1.0, "zero": 0.0})
    assert vecs.kpis == ("a", "b")
    # Player 2 sits exactly on the mean (no direction); 6 and 7 are incomplete / unranked.
    assert vecs.player_ids == (1, 3, 4, 5)
    assert vecs.vectors[1] == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    assert all(sum(x * x for x in v) == pytest.approx(1.0) for v in vecs.vectors)


def test_hand_checked_ranking_and_ties(square: pd.DataFrame) -> None:
    vecs = group_vectors(square, "X", {"a": 1.0, "b": 1.0})
    for method in ("brute", "kdtree"):
        hits = similar_players(vecs, 3, 3, method=method)
        # Orthogonal 4 and 5 tie at cosine 0 (lower id first); the mirror image 1 is -1.
        assert [h.player_id for h in hits] == [4, 5, 1]
        assert [h.similarity for h in hits] == pytest.approx([0.0, 0.0, -1.0], abs=1e-12)


def test_weights_scale_dimensions(square: pd.DataFrame) -> None:
    # Weight 4 on a doubles a's z-score: player 4 (1, -1) -> (2, -1) / sqrt(5).
    vecs = group_vectors(square, "X", {"a": 4.0, "b": 1.0})
    hits = similar_players(vecs, 3, 1)  # 3 = (2, 1) / sqrt(5)
    assert hits[0].player_id == 4
    assert hits[0].similarity == pytest.approx((2 * 2 - 1) / 5)


def test_unknown_player_raises(square: pd.DataFrame) -> None:
    vecs = group_vectors(square, "X", {"a": 1.0, "b": 1.0})
    with pytest.raises(NotFoundError):
        similar_players(vecs, 6, 3)


def test_kdtree_agrees_with_brute_force() -> None:
    rng = random.Random(11)
    kpis = ["k1", "k2", "k3", "k4", "k5"]
    rows = [(p, kpi, rng.gauss(0, 1), 50.0) for p in range(1, 121) for kpi in kpis]
    vecs = group_vectors(features(rows), "X", {k: rng.uniform(0.1, 1) for k in kpis})
    for pid in rng.sample(list(vecs.player_ids), 15):
        brute = similar_players(vecs, pid, 8)
        tree = similar_players(vecs, pid, 8, method="kdtree")
        assert [h.player_id for h in brute] == [h.player_id for h in tree]
        assert [h.similarity for h in brute] == pytest.approx([h.similarity for h in tree])
