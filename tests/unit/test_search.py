from scout.engines.search import SearchIndex, normalise_query

CLUBS = SearchIndex(
    [
        (1, "Manchester City", ["Man City", "Man. City"]),
        (2, "Manchester United", ["Man Utd", "Man United"]),
        (3, "Tottenham Hotspur", ["Spurs", "Tottenham"]),
        (4, "Brighton & Hove Albion", ["Brighton"]),
        (5, "Arsenal", []),
    ]
)


def test_normalise_query() -> None:
    assert normalise_query("  Brighton & Hove ") == "brighton and hove"
    assert normalise_query("Ødegaard") == "odegaard"


def test_aliases_resolve_exactly() -> None:
    [hit] = CLUBS.search("Spurs", limit=1, fuzzy_cutoff=80)
    assert (hit.id, hit.kind, hit.matched, hit.label) == (3, "exact", "Spurs", "Tottenham Hotspur")
    assert CLUBS.search("man city", limit=1, fuzzy_cutoff=80)[0].id == 1


def test_prefixes_and_later_words() -> None:
    assert [h.id for h in CLUBS.search("man", limit=5, fuzzy_cutoff=101)] == [1, 2]
    hits = CLUBS.search("hotspur", limit=5, fuzzy_cutoff=101)
    assert [(h.id, h.kind, h.score) for h in hits] == [(3, "prefix", 80.0)]
    assert CLUBS.search("brighton & hove", limit=5, fuzzy_cutoff=101)[0].id == 4


def test_typos_get_fuzzy_suggestions() -> None:
    hits = CLUBS.search("Arsnal", limit=3, fuzzy_cutoff=80)
    assert hits[0].id == 5 and hits[0].kind == "fuzzy"
    assert CLUBS.search("zzzz", limit=3, fuzzy_cutoff=80) == []
    assert CLUBS.search("   ", limit=3, fuzzy_cutoff=80) == []


def test_limit_and_ordering_are_stable() -> None:
    hits = CLUBS.search("ma", limit=1, fuzzy_cutoff=101)
    assert [h.id for h in hits] == [1]  # same score: alphabetical label wins


def test_prefix_matches_rank_above_fuzzy_suggestions() -> None:
    # Live data: "Saka" scored Aaron Wan-Bissaka 90 by fuzzy WRatio, above Bukayo Saka's
    # word-prefix 80, so the player typed came second. Fuzzy only fills the gaps.
    index = SearchIndex([(1, "Aaron Wan-Bissaka", []), (2, "Bukayo Saka", [])])
    hits = index.search("Saka", limit=5, fuzzy_cutoff=75)
    assert [h.label for h in hits] == ["Bukayo Saka", "Aaron Wan-Bissaka"]
    assert [h.kind for h in hits] == ["prefix", "fuzzy"]
