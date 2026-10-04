"""Benchmark: brute-force k-NN vs the hand-written k-d tree (CLAUDE.md "DSA").

Why does similar-player search use a linear scan? Run ``uv run python scripts/bench_knn.py``.
The points are random Gaussian vectors (benchmark input only, not player data), sized
like the engine's problem: ~600 Premier League players, 5-6 KPI dimensions, k = 10.

Expected picture: at n ~ 600 the tree's build cost and per-node bookkeeping cancel its
pruning, and the vectorised NumPy scan (one matrix operation) wins by a wide margin; the
tree only pays off for one-off builds queried many times at large n in low dimensions,
and its advantage shrinks as dimensions grow.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import numpy as np

from scout.dsa.kdtree import KDTree, brute_force_nearest

K = 10
QUERIES = 50
SEED = 42


def _timed(fn: Callable[[], object], repeat: int = 1) -> float:
    start = time.perf_counter()
    for _ in range(repeat):
        fn()
    return (time.perf_counter() - start) / repeat


def run(n: int, dims: int) -> tuple[float, float, float, float]:
    """Seconds per query: (tree build, tree query, python scan, numpy scan)."""
    rng = random.Random(SEED)
    points = [tuple(rng.gauss(0, 1) for _ in range(dims)) for _ in range(n)]
    queries = [tuple(rng.gauss(0, 1) for _ in range(dims)) for _ in range(QUERIES)]
    build = _timed(lambda: KDTree(points))
    tree = KDTree(points)
    tree_q = _timed(lambda: [tree.nearest(q, K) for q in queries]) / QUERIES
    scan_q = _timed(lambda: [brute_force_nearest(points, q, K) for q in queries]) / QUERIES
    matrix = np.asarray(points)

    def numpy_scan() -> None:
        for q in queries:
            d = np.linalg.norm(matrix - np.asarray(q), axis=1)
            np.argpartition(d, min(K, n - 1))[:K]

    numpy_q = _timed(numpy_scan) / QUERIES
    return build, tree_q, scan_q, numpy_q


def main() -> None:
    """Print a timing table for a few problem sizes."""
    print(f"k = {K}, {QUERIES} queries per row; times in milliseconds")
    print(f"{'n':>6} {'dims':>4} {'build':>8} {'tree/q':>8} {'scan/q':>8} {'numpy/q':>8}")
    for n, dims in ((600, 6), (600, 12), (5_000, 3), (5_000, 6), (20_000, 3)):
        build, tree_q, scan_q, numpy_q = run(n, dims)
        print(
            f"{n:>6} {dims:>4} {build * 1e3:>8.2f} {tree_q * 1e3:>8.3f} "
            f"{scan_q * 1e3:>8.3f} {numpy_q * 1e3:>8.3f}"
        )


if __name__ == "__main__":
    main()
