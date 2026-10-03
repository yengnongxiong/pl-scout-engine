import heapq
import random

import pytest

from scout.dsa.heap_topk import top_k


def test_matches_heapq_and_stable_sort_on_random_inputs() -> None:
    rng = random.Random(7)
    for _ in range(300):
        n, k = rng.randint(0, 60), rng.randint(0, 15)
        # Few distinct scores, so ties are common.
        items = [(rng.randint(0, 8), i) for i in range(n)]
        got = top_k(items, k, key=lambda x: x[0])
        assert got == heapq.nlargest(k, items, key=lambda x: x[0])
        assert got == sorted(items, key=lambda x: x[0], reverse=True)[:k]


def test_ties_keep_input_order() -> None:
    items = ["a", "b", "c", "d"]
    scores = {"a": 1.0, "b": 2.0, "c": 2.0, "d": 2.0}
    assert top_k(items, 2, key=scores.__getitem__) == ["b", "c"]


def test_edge_cases() -> None:
    assert top_k([3, 1, 2], 0, key=float) == []
    assert top_k([], 5, key=float) == []
    assert top_k([3, 1, 2], 10, key=float) == [3, 2, 1]
    assert top_k(iter([5, -1, 4]), 2, key=lambda x: -x) == [-1, 4]  # any iterable, any key


def test_nan_scores_are_rejected() -> None:
    with pytest.raises(ValueError, match="NaN"):
        top_k([1.0, float("nan")], 1, key=float)
