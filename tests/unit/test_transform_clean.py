import pytest

from scout.transform.clean import normalise_person_name, sorted_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Martin Ødegaard ", "martin odegaard"),
        ("Heung-Min Son", "heung min son"),
        ("N'Golo Kanté", "n golo kante"),
        ("Đorđe Petrović", "dorde petrovic"),
        ("J. Doe-Smith Jr.", "j doe smith jr"),
        ("", ""),
    ],
)
def test_normalise_person_name(raw: str, expected: str) -> None:
    assert normalise_person_name(raw) == expected


def test_sorted_tokens_ignores_order() -> None:
    assert sorted_tokens("Son Heung-min") == sorted_tokens("Heung-Min Son")
