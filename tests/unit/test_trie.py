import random
import string

from scout.dsa.trie import Trie


def test_prefix_search_matches_a_linear_scan_reference() -> None:
    rng = random.Random(7)
    keys = {
        "".join(rng.choices(string.ascii_lowercase[:5], k=rng.randint(1, 6))) for _ in range(300)
    }
    trie: Trie[str] = Trie()
    for key in keys:
        trie.insert(key, key)
    assert len(trie) == len(keys)
    for _ in range(200):
        prefix = "".join(rng.choices(string.ascii_lowercase[:5], k=rng.randint(0, 3)))
        expected = {k for k in keys if k.startswith(prefix)}
        assert trie.search_prefix(prefix) == expected
        assert trie.exact(prefix) == ({prefix} if prefix in keys else set())


def test_word_suffixes_find_later_words() -> None:
    trie = Trie.from_items([("manchester city", 1), ("manchester united", 2), ("leeds united", 3)])
    assert trie.search_prefix("man") == {1, 2}
    assert trie.search_prefix("manchester c") == {1}
    assert trie.search_prefix("city") == {1}
    assert trie.search_prefix("united") == {2, 3}
    assert trie.search_prefix("arsenal") == set()
    assert trie.exact("united") == {2, 3}
    assert trie.exact("unit") == set()


def test_empty_keys_and_duplicates() -> None:
    trie: Trie[int] = Trie()
    trie.insert("", 1)
    trie.insert("ab", 1)
    trie.insert("ab", 1)
    assert len(trie) == 1
    assert trie.search_prefix("") == {1}
    assert trie.search_prefix("abc") == set()
