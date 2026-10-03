import random
import string

import pytest
from rapidfuzz.distance import Levenshtein as RFLevenshtein

from scout.dsa.levenshtein import distance, similarity


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("", "", 0),
        ("abc", "", 3),
        ("", "abc", 3),
        ("kitten", "sitting", 3),
        ("flaw", "lawn", 2),
        ("martinez", "martinez", 0),
        ("son heung-min", "heung-min son", 8),
    ],
)
def test_hand_calculated_distances(a: str, b: str, expected: int) -> None:
    assert distance(a, b) == expected
    assert distance(b, a) == expected


def test_agrees_with_rapidfuzz_on_random_strings() -> None:
    rng = random.Random(11)
    alphabet = string.ascii_lowercase[:6] + " -'"
    for _ in range(500):
        a = "".join(rng.choices(alphabet, k=rng.randint(0, 15)))
        b = "".join(rng.choices(alphabet, k=rng.randint(0, 15)))
        assert distance(a, b) == RFLevenshtein.distance(a, b)
        assert similarity(a, b) == pytest.approx(100 * RFLevenshtein.normalized_similarity(a, b))


def test_similarity_bounds() -> None:
    assert similarity("", "") == 100.0
    assert similarity("abc", "abc") == 100.0
    assert similarity("abc", "xyz") == 0.0
