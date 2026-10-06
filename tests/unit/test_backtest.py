"""Backtest pieces (PRD §8.11, US-16) on hand-built frames."""

import pandas as pd
import pytest

from scout.engines.backtest import (
    Arrival,
    club_minutes,
    find_arrivals,
    most_signed,
    precision,
    relabel_season,
)

ORDER = ["CB", "FB", "DM", "CM", "AM", "W", "ST"]


def _totals(rows: list[tuple[int, str, int, str, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["player_id", "season_id", "team_id", "source", "minutes"])


TOTALS = _totals(
    [
        (1, "2025-26", 10, "vaastav", 2000.0),  # stays at club 10
        (1, "2026-27", 10, "fpl", 540.0),
        (2, "2025-26", 20, "vaastav", 1500.0),  # moves 20 -> 10
        (2, "2026-27", 10, "fpl", 360.0),
        (3, "2026-27", 10, "fpl", 0.0),  # new but has not played: not an arrival yet
        (4, "2026-27", 20, "fpl", 90.0),  # new to the league
        (5, "2025-26", 10, "vaastav", 0.0),  # registered last season, no minutes
        (5, "2026-27", 10, "fpl", 200.0),
        (6, "2025-26", 10, "understat", 900.0),  # other sources never count
        (6, "2026-27", 20, "fpl", None),
    ]
)
GROUPS = {1: "CB", 2: "ST", 3: "CM", 4: "W", 5: "DM", 6: None}
NAMES = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}


def test_relabel_only_touches_the_season_history() -> None:
    out = relabel_season(TOTALS, "2025-26")
    assert list(out["source"]) == [
        "fpl", "fpl", "fpl", "fpl", "fpl", "fpl", "fpl", "fpl", "understat", "fpl",
    ]  # fmt: skip
    assert TOTALS["source"].iloc[0] == "vaastav"  # input untouched


def test_club_minutes_keep_known_groups() -> None:
    out = club_minutes(relabel_season(TOTALS, "2025-26"), "2025-26", "fpl", GROUPS)
    assert sorted(zip(out["team_id"], out["player_id"], out["minutes"], strict=True)) == [
        (10, 1, 2000.0), (10, 5, 0.0), (20, 2, 1500.0),
    ]  # fmt: skip


def test_arrivals_are_new_to_the_club_and_have_played() -> None:
    arrivals = find_arrivals(
        TOTALS, previous="2025-26", current="2026-27", groups=GROUPS, names=NAMES, min_minutes=1
    )
    assert arrivals == {
        10: [Arrival(2, "Two", "ST", 360.0)],
        20: [Arrival(4, "Four", "W", 90.0)],
    }
    strict = find_arrivals(
        TOTALS, previous="2025-26", current="2026-27", groups=GROUPS, names=NAMES, min_minutes=100
    )
    assert strict == {10: [Arrival(2, "Two", "ST", 360.0)]}


def test_precision() -> None:
    assert precision(["ST", "CB", "W"], {"ST", "W"}) == pytest.approx(2 / 3)
    assert precision(["ST"], {"CB"}) == 0.0
    assert precision([], {"CB"}) is None


def test_most_signed_leaves_the_club_out_and_breaks_ties_in_config_order() -> None:
    arrivals = {
        1: [Arrival(1, "a", "ST", 90), Arrival(2, "b", "ST", 90)],
        2: [Arrival(3, "c", "CB", 90), Arrival(4, "d", "W", 90)],
        3: [Arrival(5, "e", "W", 90), Arrival(6, "f", None, 90)],
    }
    assert most_signed(arrivals, exclude=1, n=2, order=ORDER) == ["W", "CB"]
    assert most_signed(arrivals, exclude=3, n=3, order=ORDER) == ["ST", "CB", "W"]
    assert most_signed({}, exclude=1, n=3, order=ORDER) == []
