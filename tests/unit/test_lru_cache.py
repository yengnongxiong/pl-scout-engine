import random
from collections import OrderedDict

import pytest

from scout.dsa.lru_cache import LRUCache


def test_evicts_least_recently_used() -> None:
    cache: LRUCache[str, int] = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # a is now most recent
    cache.put("c", 3)  # evicts b
    assert "b" not in cache
    assert cache.keys_mru() == ["c", "a"]


def test_update_moves_to_front_without_growing() -> None:
    cache: LRUCache[str, int] = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    assert len(cache) == 2
    assert cache.keys_mru() == ["a", "b"]
    assert cache.get("a") == 10


def test_hit_miss_counters_pop_and_clear() -> None:
    cache: LRUCache[int, str] = LRUCache(3)
    assert cache.get(1) is None
    cache.put(1, "x")
    assert cache.get(1) == "x"
    assert (cache.hits, cache.misses) == (1, 1)
    assert cache.pop(1) == "x"
    assert cache.pop(1) is None
    cache.put(2, "y")
    cache.clear()
    assert len(cache) == 0
    assert cache.keys_mru() == []


def test_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        LRUCache(0)


def test_matches_ordereddict_reference() -> None:
    """Randomised differential test against an OrderedDict-based reference LRU."""
    rng = random.Random(42)
    capacity = 5
    cache: LRUCache[int, int] = LRUCache(capacity)
    ref: OrderedDict[int, int] = OrderedDict()
    for step in range(5000):
        key = rng.randrange(12)
        op = rng.random()
        if op < 0.5:
            got = cache.get(key)
            expected = ref.get(key)
            if key in ref:
                ref.move_to_end(key)
            assert got == expected, step
        elif op < 0.9:
            cache.put(key, step)
            ref[key] = step
            ref.move_to_end(key)
            if len(ref) > capacity:
                ref.popitem(last=False)
        else:
            assert cache.pop(key) == ref.pop(key, None)
        assert cache.keys_mru() == list(reversed(ref))
