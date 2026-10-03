"""Levenshtein edit distance by dynamic programming, for fuzzy name matching.

Used by entity resolution (PRD §7.1) to compare player names across sources after
``unidecode`` normalisation. ``distance`` keeps only two DP rows, iterating over the
shorter string for the inner loop.

Complexity: O(len(a) · len(b)) time, O(min(len(a), len(b))) space.
"""

from __future__ import annotations


def distance(a: str, b: str) -> int:
    """Minimum number of single-character insertions, deletions or substitutions."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (char_a != char_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    """Normalised similarity in [0, 100]: ``100 * (1 - distance / max(len(a), len(b)))``.

    Matches ``rapidfuzz.distance.Levenshtein.normalized_similarity`` (scaled to 100);
    two empty strings are identical (100).
    """
    longest = max(len(a), len(b))
    if longest == 0:
        return 100.0
    return 100.0 * (1.0 - distance(a, b) / longest)
