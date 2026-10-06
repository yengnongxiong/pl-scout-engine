"""Trie (prefix tree) for search-as-you-type over club and player names (PRD §12).

Each node maps one character to a child node and stores the ids of every entry whose key
passes through it, so a prefix query is a walk down the prefix followed by reading one
set, with no scan of the whole vocabulary. Keys are indexed once per word as well as in
full, so "city" finds "Manchester City" and "man c" finds it too.

Complexity (``m`` = key or prefix length, ``n`` = number of keys, ``r`` = results):

- ``insert``: O(m) time, O(m) extra nodes at worst.
- ``search_prefix``: O(m + r) time (the id set is kept at every node).
- Space: O(total characters x average ids per node); fine for ~600 players and 20 clubs.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable


class _TrieNode[V: Hashable]:
    __slots__ = ("children", "ids", "terminal")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode[V]] = {}
        self.ids: set[V] = set()
        self.terminal: set[V] = set()


class Trie[V: Hashable]:
    """Map normalised string keys to ids, with prefix lookup."""

    def __init__(self) -> None:
        self._root: _TrieNode[V] = _TrieNode()
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def insert(self, key: str, value: V) -> None:
        """Index ``value`` under ``key`` (empty keys are ignored). O(len(key))."""
        if not key:
            return
        node = self._root
        for ch in key:
            node = node.children.setdefault(ch, _TrieNode())
            node.ids.add(value)
        if value not in node.terminal:
            node.terminal.add(value)
            self._size += 1

    def insert_words(self, text: str, value: V) -> None:
        """Index ``value`` under ``text`` and under every suffix starting at a word."""
        words = text.split()
        for i in range(len(words)):
            self.insert(" ".join(words[i:]), value)

    def search_prefix(self, prefix: str) -> set[V]:
        """Ids of every key starting with ``prefix`` (all ids for an empty prefix)."""
        node = self._root
        for ch in prefix:
            child = node.children.get(ch)
            if child is None:
                return set()
            node = child
        if node is self._root:
            return {v for child in node.children.values() for v in child.ids}
        return set(node.ids)

    def exact(self, key: str) -> set[V]:
        """Ids indexed under exactly ``key``."""
        node = self._root
        for ch in key:
            child = node.children.get(ch)
            if child is None:
                return set()
            node = child
        return set(node.terminal)

    @classmethod
    def from_items(cls, items: Iterable[tuple[str, V]]) -> Trie[V]:
        """Build a trie indexing each ``(text, id)`` by every word suffix."""
        trie: Trie[V] = cls()
        for text, value in items:
            trie.insert_words(text, value)
        return trie
