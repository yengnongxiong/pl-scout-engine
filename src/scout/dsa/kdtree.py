"""k-d tree for k-nearest-neighbour search (Euclidean distance).

Similar-player search (PRD §8.10) ranks ~600 Premier League players by cosine similarity
of standardised KPI vectors. For unit-length vectors, Euclidean distance and cosine
similarity give the same order (``|a - b|^2 = 2 - 2 cos(a, b)``), so a k-d tree over the
normalised vectors can answer the same query.

The tree splits on the coordinate with the largest spread at each level (median split),
and the search prunes a subtree when the splitting plane is farther away than the
current k-th best distance. ``scripts/bench_knn.py`` shows why the engine still uses
brute force by default: with ~600 players and 5-6 dimensions, a vectorised linear scan
beats the pruning bookkeeping of a pure-Python tree, and pruning weakens as dimensions
grow (the curse of dimensionality).

Complexity: build O(n log^2 n) (sort at each level), space O(n); query O(log n + k) on
average in low dimensions, degrading towards O(n) as dimensions grow.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scout.dsa.heap_topk import top_k


@dataclass
class _Node:
    index: int  # position in the point list
    axis: int
    left: _Node | None
    right: _Node | None


class KDTree:
    """Static k-d tree over equal-length float vectors."""

    def __init__(self, points: Sequence[Sequence[float]]) -> None:
        dims = {len(p) for p in points}
        if len(dims) > 1:
            raise ValueError("all points must have the same number of dimensions")
        self.points = [tuple(float(x) for x in p) for p in points]
        self.dims = dims.pop() if dims else 0
        self.root = self._build(list(range(len(self.points))))

    def __len__(self) -> int:
        return len(self.points)

    def _build(self, indices: list[int]) -> _Node | None:
        if not indices:
            return None
        axis = max(
            range(self.dims),
            key=lambda d: (
                max(self.points[i][d] for i in indices) - min(self.points[i][d] for i in indices)
            ),
        )
        indices.sort(key=lambda i: (self.points[i][axis], i))
        mid = len(indices) // 2
        return _Node(
            index=indices[mid],
            axis=axis,
            left=self._build(indices[:mid]),
            right=self._build(indices[mid + 1 :]),
        )

    def nearest(self, query: Sequence[float], k: int) -> list[tuple[int, float]]:
        """The ``k`` nearest points as ``(index, distance)``, nearest first.

        Ties on distance are broken by the lower index, matching a stable brute-force sort.
        """
        if k <= 0 or self.root is None:
            return []
        q = tuple(float(x) for x in query)
        if len(q) != self.dims:
            raise ValueError(f"query has {len(q)} dimensions, tree has {self.dims}")
        best: list[tuple[float, int]] = []  # sorted (squared distance, index), at most k

        def consider(index: int) -> None:
            d2 = sum((a - b) ** 2 for a, b in zip(self.points[index], q, strict=True))
            entry = (d2, index)
            if len(best) < k or entry < best[-1]:
                pos = len(best)
                while pos > 0 and best[pos - 1] > entry:
                    pos -= 1
                best.insert(pos, entry)
                if len(best) > k:
                    best.pop()

        def search(node: _Node | None) -> None:
            if node is None:
                return
            consider(node.index)
            diff = q[node.axis] - self.points[node.index][node.axis]
            near, far = (node.left, node.right) if diff < 0 else (node.right, node.left)
            search(near)
            # Visit the far side only if the splitting plane is within the k-th distance.
            if len(best) < k or diff * diff <= best[-1][0]:
                search(far)

        search(self.root)
        return [(index, math.sqrt(d2)) for d2, index in best]


def brute_force_nearest(
    points: Sequence[Sequence[float]], query: Sequence[float], k: int
) -> list[tuple[int, float]]:
    """Reference linear scan: every distance, then heap top-k. O(n log k)."""
    distances = [
        (i, math.sqrt(sum((a - b) ** 2 for a, b in zip(p, query, strict=True))))
        for i, p in enumerate(points)
    ]
    return top_k(distances, k, key=lambda item: -item[1])
