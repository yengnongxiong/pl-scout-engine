"""Value-model training data (PRD §8.10 step 3), hand-checked on synthetic frames."""

import math
from datetime import date

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.ml.value_data import Valuation, attach_labels, nearest_valuation, player_seasons

CFG = load_config(PROJECT_ROOT / "config").settings.value_model
END = date(2026, 5, 24)


def test_nearest_valuation_window_and_ties() -> None:
    points = [
        Valuation(date(2026, 1, 24), 10, "transfermarkt_datasets"),  # 120 days before
        Valuation(date(2026, 5, 14), 20, "transfermarkt_datasets"),  # 10 days before
        Valuation(date(2026, 6, 3), 30, "transfermarkt_datasets"),  # 10 days after: tie
    ]
    pick = nearest_valuation(points, END, before_days=120, after_days=75)
    assert pick is not None and pick.value_eur == 30  # equal distance: the later one
    only_old = nearest_valuation(points[:1], END, before_days=120, after_days=75)
    assert only_old is not None and only_old.value_eur == 10  # boundary is inclusive
    assert nearest_valuation(points[:1], END, before_days=119, after_days=75) is None
    assert nearest_valuation([], END, before_days=120, after_days=75) is None


def _totals(rows: list[dict[str, object]]) -> pd.DataFrame:
    base = {"source": "vaastav", "fetched_at": "2026-06-01 00:00:00", "goals": None,
            "assists": None, "xg": None, "xa": None, "def_contribution": None}  # fmt: skip
    return pd.DataFrame([{**base, **r} for r in rows])


@pytest.fixture
def seasons() -> pd.DataFrame:
    totals = _totals(
        [
            # Player 1 moved mid-season: 900 min at club 10, 1800 at club 20.
            {"player_id": 1, "season_id": "2025-26", "team_id": 10, "minutes": 900,
             "goals": 2, "xg": 1.5},
            {"player_id": 1, "season_id": "2025-26", "team_id": 20, "minutes": 1800,
             "goals": 4, "xg": None},
            {"player_id": 2, "season_id": "2025-26", "team_id": 10, "minutes": 300, "goals": 0},
            {"player_id": 2, "season_id": "2025-26", "team_id": 10, "minutes": 999,
             "source": "fpl"},  # other source: ignored
        ]
    )  # fmt: skip
    return player_seasons(
        totals,
        {1: ("ST", date(2000, 5, 24)), 2: ("CB", None)},
        {"2025-26": END},
        {"2025-26": {10: (38, 57), 20: (30, 60)}},
        source="vaastav",
        seasons=["2025-26"],
        per90_stats=CFG.per90_stats,
    )


def test_player_season_features(seasons: pd.DataFrame) -> None:
    one = seasons.set_index("player_id").loc[1]
    # Main club = most minutes (club 20, which played 30 matches for 60 points).
    assert (one["team_id"], one["minutes"]) == (20, 2700)
    assert one["minutes_share"] == pytest.approx(2700 / (30 * 90))
    assert one["team_ppg"] == pytest.approx(2.0)
    assert one["age"] == pytest.approx(26.0, abs=0.01)
    assert one["goals_p90"] == pytest.approx(6 * 90 / 2700)
    # xG known at one club only: the known part counts, the unknown part adds nothing.
    assert one["xg_p90"] == pytest.approx(1.5 * 90 / 2700)
    two = seasons.set_index("player_id").loc[2]
    assert two["minutes"] == 300  # the fpl-source row is not mixed in
    assert two["age"] is None or pd.isna(two["age"])  # unknown DOB: no age, never 0
    assert pd.isna(two["xg_p90"]) and two["goals_p90"] == 0.0
    assert two["minutes_share"] == pytest.approx(300 / (38 * 90))


def test_labels_attach_with_receipts(seasons: pd.DataFrame) -> None:
    history = pd.DataFrame(
        [
            (1, date(2026, 6, 2), 40_000_000, "transfermarkt_datasets"),
            (1, date(2025, 6, 2), 10_000_000, "transfermarkt_datasets"),
        ],
        columns=["player_id", "tm_last_updated", "value_eur", "source"],
    )
    out = attach_labels(seasons, history, CFG).set_index("player_id")
    assert out.loc[1, "value_eur"] == 40_000_000
    assert out.loc[1, "log_value"] == pytest.approx(math.log(40_000_000))
    assert (out.loc[1, "value_date"], out.loc[1, "value_source"]) == (
        date(2026, 6, 2),
        "transfermarkt_datasets",
    )
    assert out.loc[2, "value_eur"] is None or pd.isna(out.loc[2, "value_eur"])


def test_value_model_config_validated() -> None:
    from scout.config import ValueModelConfig

    data = CFG.model_dump()
    with pytest.raises(ValueError, match="straddle"):
        ValueModelConfig.model_validate({**data, "quantiles": (0.6, 0.9)})
    with pytest.raises(ValueError, match="ascending"):
        ValueModelConfig.model_validate({**data, "age_bucket_edges": [30, 21]})
