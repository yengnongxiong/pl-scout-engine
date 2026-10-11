"""Hand-calculated checks of PRD §8.8 steps 1-3."""

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.engines.diagnosis import assess_groups, group_scores

CATALOGUE = load_config(PROJECT_ROOT / "config").kpis


@pytest.fixture
def scores() -> pd.DataFrame:
    club_players = pd.DataFrame(
        [
            (1, "A", "CB", 900), (1, "B", "CB", 300), (1, "E", "CB", 600),
            (2, "C", "CB", 1000), (3, "D", "CB", 500),
        ],
        columns=["team_id", "player_id", "position_group", "minutes"],
    )  # fmt: skip
    percentiles = pd.DataFrame(
        [
            ("A", "def_activity_padj_p90", 40.0), ("B", "def_activity_padj_p90", 80.0),
            ("E", "def_activity_padj_p90", None),  # below minutes threshold: no evidence
            ("C", "def_activity_padj_p90", 70.0), ("D", "def_activity_padj_p90", 90.0),
            ("A", "cbi_padj_p90", 70.0), ("C", "cbi_padj_p90", 50.0), ("D", "cbi_padj_p90", 50.0),
        ],
        columns=["player_id", "kpi", "percentile"],
    )  # fmt: skip
    return group_scores(club_players, percentiles)


def test_group_score_is_minutes_weighted(scores: pd.DataFrame) -> None:
    row = scores[(scores["team_id"] == 1) & (scores["kpi"] == "def_activity_padj_p90")].iloc[0]
    # (40*900 + 80*300) / 1200 = 50; player E (no percentile) is excluded.
    assert row["score"] == pytest.approx(50.0)
    assert row["weight_minutes"] == 1200
    assert row["players"] == 2


def test_gap_and_severity_hand_calculation(scores: pd.DataFrame) -> None:
    groups = assess_groups(1, [2, 3], scores, CATALOGUE)
    cb = groups[0]
    assert cb.position_group == "CB"
    gaps = {g.kpi: g for g in cb.gaps}
    # Benchmark = mean(70, 90) = 80; gap = 80 - 50 = 30.
    assert gaps["def_activity_padj_p90"].benchmark_score == pytest.approx(80.0)
    assert gaps["def_activity_padj_p90"].gap == pytest.approx(30.0)
    # Club is better on CBI (70 vs 50): negative gap does not offset the shortfall.
    assert gaps["cbi_padj_p90"].gap == pytest.approx(-20.0)
    # Severity = 0.30 * 30 = 9.
    assert cb.severity == pytest.approx(0.30 * 30)
    assert gaps["xg_buildup_p90"].gap is None  # no data on either side
    assert gaps["def_activity_padj_p90"].is_proxy


def test_groups_without_data_have_no_severity_and_sort_last(scores: pd.DataFrame) -> None:
    # Missing is not zero (CLAUDE.md rule 2): a group where no KPI can be compared (early
    # season in "this season only" mode, say) has no severity, not "no shortfall".
    groups = assess_groups(1, [2, 3], scores, CATALOGUE)
    assert groups[0].position_group == "CB"
    assert all(g.severity is None for g in groups[1:])
    assert [g.position_group for g in groups[1:]] == sorted(g.position_group for g in groups[1:])


def test_compared_group_without_shortfall_has_zero_severity(scores: pd.DataFrame) -> None:
    # Club 3 beats club 2 on defensive activity (90 vs 70) and matches it on CBI (50): a
    # compared group with no shortfall is a real 0.
    cb = next(g for g in assess_groups(3, [2], scores, CATALOGUE) if g.position_group == "CB")
    assert cb.severity == 0.0
