"""Disjoint-set union (union-find) for merging cross-source player records.

Entity resolution (PRD §7.1, CLAUDE.md "Known gotchas") produces pairwise "same player"
links between FPL, Understat and Transfermarkt records. Union-find turns those links into
clusters: if A~B and B~C, then A, B and C are one player even though A and C were never
compared directly.

Uses path halving and union by size. Complexity: ``find`` / ``union`` are amortised
O(alpha(n)) (inverse Ackermann, effectively constant); ``groups`` is O(n alpha(n)); space O(n).
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable


class UnionFind[T: Hashable]:
    """Disjoint sets over arbitrary hashable items; items are added on first use."""

    def __init__(self, items: Iterable[T] = ()) -> None:
        self._parent: dict[T, T] = {}
        self._size: dict[T, int] = {}
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._parent)

    def __contains__(self, item: object) -> bool:
        return item in self._parent

    def add(self, item: T) -> None:
        """Add ``item`` as a singleton set if it is new. O(1)."""
        if item not in self._parent:
            self._parent[item] = item
            self._size[item] = 1

    def find(self, item: T) -> T:
        """Return the representative of ``item``'s set (path halving). Amortised O(alpha(n))."""
        self.add(item)
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, a: T, b: T) -> T:
        """Merge the sets of ``a`` and ``b`` (union by size); return the new root."""
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return root_a
        if self._size[root_a] < self._size[root_b]:
            root_a, root_b = root_b, root_a
        self._parent[root_b] = root_a
        self._size[root_a] += self._size.pop(root_b)
        return root_a

    def connected(self, a: T, b: T) -> bool:
        """Whether ``a`` and ``b`` are in the same set."""
        return self.find(a) == self.find(b)

    def groups(self) -> list[set[T]]:
        """All sets, each as a Python set. O(n alpha(n))."""
        out: dict[T, set[T]] = {}
        for item in list(self._parent):
            out.setdefault(self.find(item), set()).add(item)
        return list(out.values())
