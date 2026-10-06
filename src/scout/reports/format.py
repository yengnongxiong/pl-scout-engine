"""Number and date formatting for reports (PRD §13 rounding rules).

Missing values are "Not available", never 0 (CLAUDE.md rule 2). The grounding validator
(``reports.grounding``) understands exactly these formats, so templates must format numbers
through these functions.
"""

from __future__ import annotations

import math
from datetime import date

NOT_AVAILABLE = "Not available"
EUR_PER_MILLION = 1_000_000
SMALL_RATE = 1.0  # per-90 rates below this (xG, xA) get a second decimal


def per90(value: float | None) -> str:
    """A per-90 rate: one decimal, two below 1 so xG-type rates stay readable."""
    if value is None or math.isnan(value):
        return NOT_AVAILABLE
    return f"{value:.2f}" if abs(value) < SMALL_RATE else f"{value:.1f}"


def ordinal(value: float | None) -> str:
    """A percentile as an ordinal ("72nd")."""
    if value is None or math.isnan(value):
        return NOT_AVAILABLE
    n = round(value)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def score(value: float | None) -> str:
    """A 0-100 score, one decimal."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{value:.1f}"


def points(value: float | None) -> str:
    """Percentile points, whole and signed ("+12", "-3")."""
    if value is None or math.isnan(value):
        return NOT_AVAILABLE
    return f"{round(value):+d}"


def whole(value: float | None) -> str:
    """A whole number with thousands separators."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{round(value):,}"


def minutes(value: float | None) -> str:
    """Minutes ("1,234 minutes")."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{round(value):,} minutes"


def age(value: float | None) -> str:
    """Age in years, one decimal."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{value:.1f}"


def eur_m(value: float | None) -> str:
    """Transfermarkt-style euros in millions ("€45.0m")."""
    if value is None or math.isnan(value):
        return NOT_AVAILABLE
    return f"€{value / EUR_PER_MILLION:.1f}m"


def share(value: float | None) -> str:
    """A share in [0, 1] as a whole percentage."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{round(value * 100)}%"


def cosine(value: float | None) -> str:
    """A cosine similarity, two decimals."""
    return NOT_AVAILABLE if value is None or math.isnan(value) else f"{value:.2f}"


def iso_date(value: date | str | None) -> str:
    """A calendar date as ISO ``YYYY-MM-DD``; timestamps keep their date part."""
    if value is None or value == "":
        return NOT_AVAILABLE
    if isinstance(value, date):
        return value.isoformat()
    return value[:10]
