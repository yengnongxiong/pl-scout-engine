"""Top-k selection with a hand-written bounded min-heap.

Shortlists (PRD §8.9) and similar-player lists (PRD §8.10) need the k best of a few
hundred scored players. Sorting everything is O(n log n); keeping a min-heap of the k
best seen so far is O(n log k): each new item is compared with the heap root (the worst
item kept) and only replaces it when better. With k = 10 and n = 600 that is a handful of
comparisons per player instead of a full sort.

Ties are deterministic: among equal scores the item seen first wins, so the result equals
a stable descending sort truncated to k (what ``heapq.nlargest`` documents).

Complexity: time O(n log k) for n items, space O(k).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable


class _BoundedMinHeap[T]:
    """Array-backed binary min-heap of ``(score, -index, item)`` entries, capacity k.

    Ordering by ``(score, -index)`` makes the root the worst entry kept: the lowest
    score, and among equal scores the one seen last.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.entries: list[tuple[float, int, T]] = []

    @staticmethod
    def _less(a: tuple[float, int, T], b: tuple[float, int, T]) -> bool:
        return (a[0], a[1]) < (b[0], b[1])

    def offer(self, entry: tuple[float, int, T]) -> None:
        """Keep ``entry`` if it is among the k best so far. O(log k)."""
        if len(self.entries) < self.capacity:
            self.entries.append(entry)
            self._sift_up(len(self.entries) - 1)
        elif self._less(self.entries[0], entry):
            self.entries[0] = entry
            self._sift_down(0)

    def _sift_up(self, i: int) -> None:
        heap = self.entries
        while i > 0:
            parent = (i - 1) // 2
            if not self._less(heap[i], heap[parent]):
                return
            heap[i], heap[parent] = heap[parent], heap[i]
            i = parent

    def _sift_down(self, i: int) -> None:
        heap, n = self.entries, len(self.entries)
        while True:
            smallest, left, right = i, 2 * i + 1, 2 * i + 2
            if left < n and self._less(heap[left], heap[smallest]):
                smallest = left
            if right < n and self._less(heap[right], heap[smallest]):
                smallest = right
            if smallest == i:
                return
            heap[i], heap[smallest] = heap[smallest], heap[i]
            i = smallest


def top_k[T](items: Iterable[T], k: int, key: Callable[[T], float]) -> list[T]:
    """The ``k`` items with the highest ``key``, best first.

    Args:
        items: Candidates, consumed once.
        k: How many to keep; ``k <= 0`` returns an empty list.
        key: Score for each item (higher is better).

    Returns:
        At most ``k`` items sorted by score descending; equal scores keep input order.

    Raises:
        ValueError: If a score is NaN (it has no place in a ranking; filter it out first).
    """
    if k <= 0:
        return []
    heap: _BoundedMinHeap[T] = _BoundedMinHeap(k)
    for index, item in enumerate(items):
        score = float(key(item))
        if math.isnan(score):
            raise ValueError("top_k scores must not be NaN")
        heap.offer((score, -index, item))
    ranked = sorted(heap.entries, key=lambda e: (e[0], e[1]), reverse=True)
    return [item for _, _, item in ranked]
