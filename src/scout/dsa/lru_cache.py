"""LRU cache: hash map + doubly linked list, for hot API endpoints (PRD §12).

The hash map gives O(1) lookup of a node; the doubly linked list keeps recency order so
moving a node to the front and evicting the tail are O(1) pointer updates. Sentinel head
and tail nodes remove edge cases for empty lists.

Complexity: ``get``, ``put`` and ``pop`` are O(1) time; space is O(capacity).
"""

from __future__ import annotations

from collections.abc import Hashable


class _Node[K: Hashable, V]:
    __slots__ = ("key", "next", "prev", "value")

    def __init__(self, key: K | None, value: V | None) -> None:
        self.key = key
        self.value = value
        self.prev: _Node[K, V] | None = None
        self.next: _Node[K, V] | None = None


class LRUCache[K: Hashable, V]:
    """Fixed-capacity least-recently-used cache.

    Args:
        capacity: Maximum number of entries (>= 1).
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._map: dict[K, _Node[K, V]] = {}
        self._head: _Node[K, V] = _Node(None, None)  # most recent side
        self._tail: _Node[K, V] = _Node(None, None)  # least recent side
        self._head.next = self._tail
        self._tail.prev = self._head
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: object) -> bool:
        return key in self._map

    def _unlink(self, node: _Node[K, V]) -> None:
        assert node.prev is not None and node.next is not None
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node: _Node[K, V]) -> None:
        first = self._head.next
        assert first is not None
        node.prev = self._head
        node.next = first
        first.prev = node
        self._head.next = node

    def get(self, key: K) -> V | None:
        """Return the cached value (marking it most recent) or ``None`` on a miss. O(1)."""
        node = self._map.get(key)
        if node is None:
            self.misses += 1
            return None
        self.hits += 1
        self._unlink(node)
        self._push_front(node)
        return node.value

    def put(self, key: K, value: V) -> None:
        """Insert or update ``key``; evict the least recently used entry if full. O(1)."""
        node = self._map.get(key)
        if node is not None:
            node.value = value
            self._unlink(node)
            self._push_front(node)
            return
        if len(self._map) >= self.capacity:
            lru = self._tail.prev
            assert lru is not None and lru is not self._head and lru.key is not None
            self._unlink(lru)
            del self._map[lru.key]
        node = _Node(key, value)
        self._map[key] = node
        self._push_front(node)

    def pop(self, key: K) -> V | None:
        """Remove ``key`` and return its value, or ``None`` if absent. O(1)."""
        node = self._map.pop(key, None)
        if node is None:
            return None
        self._unlink(node)
        return node.value

    def clear(self) -> None:
        """Remove every entry. O(n) to release references."""
        self._map.clear()
        self._head.next = self._tail
        self._tail.prev = self._head

    def keys_mru(self) -> list[K]:
        """Keys from most to least recently used. O(n)."""
        out: list[K] = []
        node = self._head.next
        while node is not None and node is not self._tail:
            assert node.key is not None
            out.append(node.key)
            node = node.next
        return out
