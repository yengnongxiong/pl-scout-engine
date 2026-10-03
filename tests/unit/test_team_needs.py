"""Hand-calculated checks of team-level needs (PRD §8.8 step 7)."""

from typing import get_args

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, TeamMatchColumn, load_config
from scout.engines.team_needs import (
    VALUE_COLUMNS,
    assess_team,
    team_kpi_values,
    team_percentiles,
)

CONFIG = load_config(PROJECT_ROOT / "config")
TEAM_KPIS = CONFIG.kpis.team_kpis
CUR, PREV = "2026-27", "2025-26"


def totals_row(team_id: int, season_id: str, as_of: str, **stats: tuple[float, int]) -> dict:
    """A ``team_season.sql`` row; columns not given have no data (NULL total, 0 matches)."""
    row: dict[str, object] = {"team_id": team_id, "season_id": season_id, "source": "understat"}
    for col in get_args(TeamMatchColumn):
        total, matches = stats.get(col, (None, 0))
        row[f"{col}_total"], row[f"{col}_matches"] = total, matches
    row["as_of"] = as_of
    return row


@pytest.fixture
def totals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            totals_row(1, CUR, "2026-09-20 08:00:00", xg=(3.0, 2), ppda=(20.0, 2)),
            totals_row(1, PREV, "2026-05-30 08:00:00", xg=(38.0, 38)),
            totals_row(2, PREV, "2026-05-30 09:00:00", xg=(19.0, 38)),  # no current rows yet
        ]
    )


def values_for(df: pd.DataFrame, team: int, kpi: str) -> pd.Series:
    return df[(df["team_id"] == team) & (df["kpi"] == kpi)].iloc[0]


def test_current_mode_rates(totals: pd.DataFrame) -> None:
    out = team_kpi_values(
        totals, TEAM_KPIS, current=CUR, previous=None, lam=0.5, prev_minutes_cap=2000
    )
    xg = values_for(out, 1, "xg_p90")
    assert xg["value"] == pytest.approx(1.5)  # 3.0 xG over 180 minutes, per 90
    assert (xg["matches"], xg["previous_matches"], xg["effective_minutes"]) == (2, 0, 180)
    # PPDA is a ratio: mean of per-match values (20.0 / 2), not per 90.
    assert values_for(out, 1, "ppda")["value"] == pytest.approx(10.0)
    # No data is no row (never 0): no set-piece split, and club 2 has no current matches.
    assert "set_piece_xg_p90" not in set(out["kpi"])
    assert 2 not in set(out["team_id"])
    assert list(out.columns) == VALUE_COLUMNS


def test_blended_mode_hand_calculation(totals: pd.DataFrame) -> None:
    out = team_kpi_values(
        totals, TEAM_KPIS, current=CUR, previous=PREV, lam=0.5, prev_minutes_cap=2000
    )
    xg = values_for(out, 1, "xg_p90")
    # m_cur = 180; m_prev = min(38 x 90, 2000) = 2000, weighted 0.5 -> 1000.
    # (180 x 1.5 + 1000 x 1.0) / 1180 = 1270 / 1180.
    assert xg["value"] == pytest.approx(1270 / 1180)
    assert (xg["matches"], xg["previous_matches"], xg["effective_minutes"]) == (2, 38, 1180)
    assert xg["as_of"] == "2026-09-20T08:00:00"  # newest receipt behind the blend
    # Club 2 has only last season: that rate is used alone.
    town = values_for(out, 2, "xg_p90")
    assert town["value"] == pytest.approx(0.5)
    assert (town["matches"], town["previous_matches"]) == (0, 38)
    # PPDA for club 1 exists only this season, so nothing from last season is blended in.
    assert values_for(out, 1, "ppda")["previous_matches"] == 0


@pytest.fixture
def ranked() -> pd.DataFrame:
    rows = [
        (team, kpi, value, 3, 0, 270.0, "understat", f"2026-09-2{team} 08:00:00")
        for kpi, values in (("xg_p90", (1.0, 2.0, 3.0)), ("xga_p90", (1.0, 2.0, 3.0)))
        for team, value in zip((1, 2, 3), values, strict=True)
    ]
    rows.append((99, "xg_p90", 9.0, 3, 0, 270.0, "understat", "2026-09-29 08:00:00"))
    values = pd.DataFrame(rows, columns=VALUE_COLUMNS)
    return team_percentiles(values, [1, 2, 3], TEAM_KPIS)


def test_league_percentiles_flip_inverse_kpis(ranked: pd.DataFrame) -> None:
    def pct(kpi: str) -> dict[int, float]:
        sub = ranked[ranked["kpi"] == kpi]
        return dict(zip(sub["team_id"], sub["percentile"], strict=True))

    assert pct("xg_p90") == {1: 0.0, 2: 50.0, 3: 100.0}
    assert pct("xga_p90") == {1: 100.0, 2: 50.0, 3: 0.0}  # lower xG against is better
    assert set(ranked["n_peers"]) == {3}  # club 99 is not in this season's league


def test_assess_team_gaps_and_mapping(ranked: pd.DataFrame) -> None:
    needs = assess_team(3, [1, 2], ranked, TEAM_KPIS)
    # xG for: club p100 vs benchmark mean p25 -> ahead, not a need.
    assert [n.kpi for n in needs] == ["xga_p90"]
    xga = needs[0]
    # Club p0 vs benchmark mean of p100 and p50 = 75 -> gap 75.
    assert (xga.club_percentile, xga.benchmark_percentile, xga.gap) == (0.0, 75.0, 75.0)
    assert (xga.club_value, xga.benchmark_value) == (3.0, 1.5)
    assert xga.responsible_groups == tuple(TEAM_KPIS["xga_p90"].responsible_groups)
    assert (xga.n_peers, xga.benchmark_clubs, xga.source) == (3, 2, "understat")
    assert xga.as_of == "2026-09-23T08:00:00"
    assert not xga.higher_is_better


def test_assess_team_skips_kpis_without_evidence(ranked: pd.DataFrame) -> None:
    assert assess_team(42, [1, 2], ranked, TEAM_KPIS) == []  # club has no data
    assert assess_team(1, [77], ranked, TEAM_KPIS) == []  # benchmark has no data
    needs = assess_team(1, [2, 3], ranked, TEAM_KPIS)
    assert [n.kpi for n in needs] == ["xg_p90"]  # ahead on xG against
    assert needs[0].gap == pytest.approx(75.0)


def test_empty_values_rank_to_empty_frame() -> None:
    out = team_percentiles(pd.DataFrame(columns=VALUE_COLUMNS), [1], TEAM_KPIS)
    assert out.empty and {"percentile", "n_peers"} <= set(out.columns)
