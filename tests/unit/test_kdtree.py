import math
import random

import pytest

from scout.dsa.kdtree import KDTree, brute_force_nearest


def _sorted_reference(
    points: list[tuple[float, ...]], query: tuple[float, ...], k: int
) -> list[tuple[int, float]]:
    """Independent reference: math.dist on every point, stable sort by distance."""
    ranked = sorted(range(len(points)), key=lambda i: (math.dist(points[i], query), i))
    return [(i, math.dist(points[i], query)) for i in ranked[:k]]


def _same(a: list[tuple[int, float]], b: list[tuple[int, float]]) -> bool:
    return [i for i, _ in a] == [i for i, _ in b] and all(
        x == pytest.approx(y) for (_, x), (_, y) in zip(a, b, strict=True)
    )


@pytest.mark.parametrize("dims", [1, 2, 5, 8])
def test_matches_reference_on_random_points(dims: int) -> None:
    rng = random.Random(dims)
    for _ in range(40):
        n, k = rng.randint(0, 80), rng.randint(0, 12)
        # Rounded coordinates so equal distances (ties) actually happen.
        points = [tuple(round(rng.gauss(0, 1), 1) for _ in range(dims)) for _ in range(n)]
        query = tuple(round(rng.gauss(0, 1), 1) for _ in range(dims))
        expected = _sorted_reference(points, query, k)
        assert _same(KDTree(points).nearest(query, k), expected)
        assert _same(brute_force_nearest(points, query, k), expected)


def test_duplicates_and_edge_cases() -> None:
    tree = KDTree([(0.0, 0.0), (1.0, 1.0), (1.0, 1.0), (5.0, 5.0)])
    assert len(tree) == 4
    assert [i for i, _ in tree.nearest((1.0, 1.0), 2)] == [1, 2]
    assert tree.nearest((0.0, 0.0), 0) == []
    assert KDTree([]).nearest((0.0,), 3) == []
    with pytest.raises(ValueError, match="dimensions"):
        tree.nearest((1.0,), 1)
    with pytest.raises(ValueError, match="same number"):
        KDTree([(1.0,), (1.0, 2.0)])


def test_unit_vectors_rank_like_cosine() -> None:
    def unit(v: tuple[float, ...]) -> tuple[float, ...]:
        n = math.sqrt(sum(x * x for x in v))
        return tuple(x / n for x in v)

    rng = random.Random(3)
    points = [unit(tuple(rng.gauss(0, 1) for _ in range(4))) for _ in range(50)]
    query = unit((1.0, 0.5, -0.2, 0.1))
    by_cosine = sorted(
        range(len(points)), key=lambda i: -sum(a * b for a, b in zip(points[i], query, strict=True))
    )
    assert [i for i, _ in KDTree(points).nearest(query, 5)] == by_cosine[:5]
