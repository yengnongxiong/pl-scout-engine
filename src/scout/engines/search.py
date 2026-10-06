"""Club and player search: trie prefix matches first, fuzzy suggestions second (US-01).

Names and aliases are normalised (accents, case, punctuation, "&" as "and") and indexed in
a trie under every word suffix, so "spurs", "man c" and "city" all resolve as you type.
When prefixes find too little (a typo such as "Arsnal"), the remaining slots are filled
with fuzzy suggestions ranked by ``rapidfuzz`` WRatio above a configured cut-off, so
unknown input still shows suggestions instead of an empty list.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process

from scout.dsa.trie import Trie
from scout.transform.clean import normalise_person_name

MatchKind = Literal["exact", "prefix", "fuzzy"]
EXACT_SCORE = 100.0
PREFIX_SCORE = 90.0  # a prefix of the start of a name or alias
WORD_PREFIX_SCORE = 80.0  # a prefix of a later word ("city" in "manchester city")


def normalise_query(text: str) -> str:
    """Normalise a name or query for matching."""
    return normalise_person_name(text.replace("&", " and "))


@dataclass(frozen=True)
class SearchHit:
    """One search result with how it matched."""

    id: int
    label: str
    matched: str
    kind: MatchKind
    score: float


class SearchIndex:
    """Prefix + fuzzy search over ``(id, display label, alternative names)`` entries."""

    def __init__(self, entries: Sequence[tuple[int, str, Sequence[str]]]) -> None:
        self._labels = {eid: label for eid, label, _ in entries}
        self._keys: list[tuple[str, int, str]] = []  # normalised key, id, original spelling
        for eid, label, alts in entries:
            for spelling in dict.fromkeys([label, *alts]):
                key = normalise_query(spelling)
                if key:
                    self._keys.append((key, eid, spelling))
        self._trie: Trie[int] = Trie.from_items((k, i) for k, i, _ in self._keys)

    def search(self, query: str, *, limit: int, fuzzy_cutoff: float) -> list[SearchHit]:
        """Best matches for ``query``: exact, then prefix, then fuzzy; ties by label."""
        q = normalise_query(query)
        if not q:
            return []
        best: dict[int, SearchHit] = {}

        def offer(hit: SearchHit) -> None:
            old = best.get(hit.id)
            if old is None or hit.score > old.score:
                best[hit.id] = hit

        candidates = self._trie.search_prefix(q)
        for key, eid, spelling in self._keys:
            if eid not in candidates:
                continue
            if key == q:
                offer(SearchHit(eid, self._labels[eid], spelling, "exact", EXACT_SCORE))
            elif key.startswith(q):
                offer(SearchHit(eid, self._labels[eid], spelling, "prefix", PREFIX_SCORE))
            elif any(w.startswith(q) for w in _suffixes(key)):
                offer(SearchHit(eid, self._labels[eid], spelling, "prefix", WORD_PREFIX_SCORE))
        if len(best) < limit:
            for _, score, idx in process.extract(
                q, [k for k, _, _ in self._keys], scorer=fuzz.WRatio, limit=None
            ):
                if score < fuzzy_cutoff:
                    continue
                _, eid, spelling = self._keys[idx]
                if eid not in best:
                    offer(SearchHit(eid, self._labels[eid], spelling, "fuzzy", float(score)))
        ranked = sorted(best.values(), key=lambda h: (-h.score, h.label, h.id))
        return ranked[:limit]


def _suffixes(key: str) -> list[str]:
    words = key.split()
    return [" ".join(words[i:]) for i in range(1, len(words))]
