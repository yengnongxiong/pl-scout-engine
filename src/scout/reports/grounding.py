"""Grounding validator: every number and proper noun in a report must be in the fact sheet.

PRD §9 step 4. A rewritten report (local LLM) is only shown if this passes; otherwise the
template report is used and the violations are logged. The template report itself is
checked too, so a template change that slips in an unsourced number fails its tests.

How text is read:

- **Dates** (``2026-09-30``) and **season ids** (``2026-27``) must appear verbatim in the
  fact sheet.
- **Money** (``€45.0m``) must match a euro amount in the sheet, in millions.
- **Other numbers** (``2.4``, ``72nd``, ``1,234``, ``+12``, ``75%``) must match a sheet
  number after the rounding the text shows (one decimal shown = within 0.05). A signed
  number must match with its sign; an unsigned one may match either sign ("trails by 12"
  for a gap of -12 is fine).
- **Proper nouns**: capitalised words must appear somewhere in the sheet's text or in the
  reference report (the template output the rewrite started from), or be common English
  words; this catches invented names, clubs and competitions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from scout.reports.facts import FactSheet, allowed_numbers, allowed_text

logger = logging.getLogger(__name__)

# Digit lookarounds rather than \b, so a date inside an ISO timestamp ("...-01T00:00") counts.
_DATE = re.compile(r"(?<![\d-])\d{4}-\d{2}-\d{2}(?!\d)")
_SEASON = re.compile(r"(?<![\d-])\d{4}-\d{2}(?![\d-])")
_MONEY = re.compile(r"€\s?(\d+(?:\.\d+)?)\s?m\b")
_NUMBER = re.compile("(?<![\\d.,])([+\\-\u2212]?)" r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
_APOSTROPHES = "'\u2019"
_WORD = re.compile(f"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ{_APOSTROPHES}\\-]*")
_SIGNS = {"+": 1.0, "-": -1.0, "\u2212": -1.0}

# Capitalised words that are ordinary English, not names (sentence starters etc.).
COMMON_WORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "across",
        "after",
        "again",
        "against",
        "all",
        "also",
        "although",
        "among",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "despite",
        "did",
        "do",
        "does",
        "during",
        "each",
        "either",
        "even",
        "every",
        "few",
        "for",
        "from",
        "further",
        "given",
        "had",
        "has",
        "have",
        "he",
        "her",
        "here",
        "his",
        "how",
        "however",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "less",
        "like",
        "many",
        "may",
        "meanwhile",
        "more",
        "moreover",
        "most",
        "much",
        "must",
        "neither",
        "no",
        "nor",
        "not",
        "notably",
        "now",
        "of",
        "on",
        "once",
        "one",
        "only",
        "or",
        "other",
        "others",
        "our",
        "over",
        "overall",
        "own",
        "per",
        "perhaps",
        "rather",
        "same",
        "she",
        "should",
        "since",
        "so",
        "some",
        "still",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "though",
        "through",
        "thus",
        "to",
        "too",
        "under",
        "unlike",
        "until",
        "up",
        "upon",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whereas",
        "which",
        "while",
        "who",
        "whose",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "yet",
        "additionally",
        "furthermore",
        "importantly",
    ]
)


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of validating one text against a fact sheet."""

    ok: bool
    violations: list[str] = field(default_factory=list)


def _matches(
    value: float, decimals: int, allowed: set[float], *, signed: bool, tolerance: float
) -> bool:
    """Is ``value`` (shown with ``decimals`` places) a rounding of an allowed number?"""
    half_step = 0.5 * 10.0**-decimals
    for a in allowed:
        candidates = (a,) if signed else (a, -a)
        for c in candidates:
            if abs(c - value) <= half_step + tolerance * max(1.0, abs(c)):
                return True
    return False


def check_numbers(text: str, allowed: set[float], tolerance: float) -> list[str]:
    """Numbers in ``text`` that no fact-sheet number rounds to."""
    violations: list[str] = []
    for m in _MONEY.finditer(text):
        raw = m.group(1)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not _matches(float(raw), decimals, allowed, signed=False, tolerance=tolerance):
            violations.append(f"money {m.group(0)!r} is not in the fact sheet")
    remainder = _MONEY.sub(" ", text)
    for m in _NUMBER.finditer(remainder):
        sign, whole, frac = m.group(1), m.group(2), m.group(3)
        value = float(whole.replace(",", "") + (f".{frac}" if frac else ""))
        if sign:
            value *= _SIGNS[sign]
        decimals = len(frac) if frac else 0
        if not _matches(value, decimals, allowed, signed=bool(sign), tolerance=tolerance):
            violations.append(f"number {m.group(0)!r} is not in the fact sheet")
    return violations


def check_dates(text: str, sheet_text: str) -> tuple[list[str], str]:
    """Dates and season ids not in the sheet; returns the text with them blanked out."""
    violations: list[str] = []
    known_dates = set(_DATE.findall(sheet_text))
    for found in _DATE.findall(text):
        if found not in known_dates:
            violations.append(f"date {found!r} is not in the fact sheet")
    text = _DATE.sub(" ", text)
    known_seasons = set(_SEASON.findall(sheet_text))
    for found in _SEASON.findall(text):
        if found not in known_seasons:
            violations.append(f"season {found!r} is not in the fact sheet")
    return violations, _SEASON.sub(" ", text)


def check_proper_nouns(text: str, vocabulary: set[str]) -> list[str]:
    """Capitalised words that are neither in the vocabulary nor common English."""
    violations: list[str] = []
    seen: set[str] = set()
    for word in _WORD.findall(text):
        if not word[0].isupper():
            continue
        key = _normalise(word)
        if key in vocabulary or key in COMMON_WORDS or key in seen:
            continue
        seen.add(key)
        violations.append(f"name {word!r} is not in the fact sheet")
    return violations


def _normalise(word: str) -> str:
    """Case-fold and drop possessives ("Rovers's", "Rovers'") and edge hyphens."""
    key = word.casefold()
    for apostrophe in _APOSTROPHES:
        key = key.removesuffix(f"{apostrophe}s")
    return key.strip(_APOSTROPHES + "-")


def _vocabulary(*texts: str) -> set[str]:
    return {_normalise(w) for t in texts for w in _WORD.findall(t)}


def validate(
    text: str, sheet: FactSheet, *, reference: str = "", tolerance: float = 1e-6
) -> GroundingResult:
    """Check every number, date and proper noun in ``text`` against ``sheet``.

    Args:
        text: Report text to validate.
        sheet: The fact sheet the report must be grounded in.
        reference: Template report the text was derived from (its wording is allowed;
            its numbers were checked separately).
        tolerance: Relative tolerance on top of the rounding the text shows.
    """
    sheet_text = allowed_text(sheet)
    violations, rest = check_dates(text, sheet_text)
    violations += check_numbers(rest, allowed_numbers(sheet), tolerance)
    violations += check_proper_nouns(text, _vocabulary(sheet_text, reference))
    if violations:
        logger.warning(
            "report failed grounding",
            extra={"player_id": sheet.player_id, "violations": violations},
        )
    return GroundingResult(ok=not violations, violations=violations)
