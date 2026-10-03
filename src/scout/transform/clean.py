"""Name normalisation shared by entity resolution and search.

Sources spell names differently ("Heung-Min Son" / "Son Heung-min", "Ødegaard" /
"Odegaard"). Normalising before comparison removes accents (``unidecode``), case,
punctuation and token order differences that carry no identity information.
"""

from __future__ import annotations

import re

from unidecode import unidecode

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise_person_name(name: str) -> str:
    """Lower-case ASCII name with punctuation turned into spaces and whitespace collapsed.

    >>> normalise_person_name("  Martin Ødegaard ")
    'martin odegaard'
    >>> normalise_person_name("Heung-Min Son")
    'heung min son'
    """
    ascii_name = unidecode(name).casefold()
    return " ".join(_PUNCT.sub(" ", ascii_name).split())


def sorted_tokens(name: str) -> str:
    """Normalised tokens in sorted order, so "Son Heung-min" equals "Heung-Min Son"."""
    return " ".join(sorted(normalise_person_name(name).split()))
