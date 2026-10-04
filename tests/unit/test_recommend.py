"""Pure helpers of the recommendation engine (PRD §8.9)."""

from datetime import date

import pytest

from scout.engines.recommend import (
    Filters,
    MarketValue,
    _filter_reason,
    age_on,
    preferred_market_value,
)

PRECEDENCE = ["override", "transfermarkt", "transfermarkt_datasets"]


def _mv(source: str, value: int, *, stale: bool = False) -> dict:
    return {
        "source": source,
        "value_eur": value,
        "tm_last_updated": date(2026, 6, 10),
        "is_stale": stale,
        "fetched_at": "2026-09-01 08:00:00",
    }


def test_market_value_precedence() -> None:
    rows = [_mv("transfermarkt_datasets", 10, stale=True), _mv("transfermarkt", 20)]
    best = preferred_market_value(rows, PRECEDENCE)
    assert best == MarketValue(20, date(2026, 6, 10), "transfermarkt", False, "2026-09-01 08:00:00")
    assert preferred_market_value([*rows, _mv("override", 30)], PRECEDENCE).value_eur == 30
    stale = preferred_market_value(rows[:1], PRECEDENCE)
    assert stale is not None and stale.is_stale
    assert preferred_market_value([], PRECEDENCE) is None


def test_age_on() -> None:
    assert age_on(date(2000, 1, 1), date(2026, 1, 1)) == pytest.approx(26.0, abs=0.01)
    assert age_on(None, date(2026, 1, 1)) is None


def _profile(status: str | None = "a", team: int = 2) -> dict:
    return {"fpl_status": status, "current_team_id": team}


def _reason(filters: Filters, **kw: object) -> str | None:
    args: dict = {"age": 25.0, "minutes": 1500.0, "value": None, "filters": filters,
                  "excluded_statuses": ["u", "n"]}  # fmt: skip
    args.update(kw)
    profile = args.pop("profile", _profile())
    return _filter_reason(profile, **args)


def test_hard_filters() -> None:
    value = MarketValue(30_000_000, date(2026, 6, 10), "transfermarkt", False, "x")
    assert _reason(Filters()) is None
    assert _reason(Filters(), profile=_profile("u")) == "unavailable"
    assert _reason(Filters(exclude_team_ids=(2,))) == "excluded club"
    assert _reason(Filters(max_age=24)) == "outside age range"
    assert _reason(Filters(min_age=26)) == "outside age range"
    assert _reason(Filters(min_age=20), age=None) == "age unknown"
    assert _reason(Filters(min_minutes=2000)) == "too few minutes"
    assert _reason(Filters(min_minutes=2000), minutes=None) == "too few minutes"
    # A budget can't be checked without a value: excluded, never assumed cheap.
    assert _reason(Filters(max_value_eur=40_000_000)) == "no market value"
    assert _reason(Filters(max_value_eur=20_000_000), value=value) == "over budget"
    assert _reason(Filters(max_value_eur=40_000_000), value=value) is None
