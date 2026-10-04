"""Value model (PRD §8.10 step 3) on synthetic seasons with a known value structure."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.ml.value_model import (
    CAVEAT,
    Baseline,
    age_bucket,
    band_label,
    error_metrics,
    feature_matrix,
    feature_names,
    informative_columns,
    metadata,
    score_players,
    train_value_model,
)

BASE = load_config(PROJECT_ROOT / "config")
CFG = BASE.settings.value_model.model_copy(update={"max_iter": 150})
GROUPS = list(BASE.kpis.position_groups)


def synthetic_seasons(seed: int = 0, n: int = 220) -> pd.DataFrame:
    """Three seasons where value rises with xG, minutes share and club strength."""
    rng = np.random.default_rng(seed)
    rows = []
    for season in ("2022-23", "2023-24", "2024-25"):
        for i in range(n):
            xg = rng.uniform(0, 0.7)
            share = rng.uniform(0.2, 1.0)
            ppg = rng.uniform(0.8, 2.4)
            age = rng.uniform(18, 34)
            log_value = 14.5 + 2.0 * xg + 1.2 * share + 0.6 * ppg - 0.004 * (age - 26) ** 2
            rows.append(
                {
                    "player_id": i, "season_id": season, "position_group": GROUPS[i % 7],
                    "age": age, "minutes": share * 3420, "minutes_share": share,
                    "team_ppg": ppg, "goals_p90": xg * 0.9, "assists_p90": None,
                    "xg_p90": xg, "xa_p90": rng.uniform(0, 0.3),
                    "def_contribution_p90": None,
                    "log_value": log_value + rng.normal(0, 0.15),
                }
            )  # fmt: skip
    return pd.DataFrame(rows)


def test_feature_matrix_keeps_missing_as_nan() -> None:
    frame = pd.DataFrame(
        [{"age": 25.0, "minutes": 900, "minutes_share": 0.5, "team_ppg": None,
          "goals_p90": 0.2, "xg_p90": None, "position_group": "ST"}]
    )  # fmt: skip
    x = feature_matrix(frame, ["goals", "xg"], GROUPS)
    assert feature_names(["goals", "xg"])[-1] == "position_group"
    assert "minutes" not in feature_names(["goals"])  # scale-free inputs only
    assert x.shape == (1, 7)
    assert x[0, 0] == 25.0 and x[0, 1] == 625.0  # age and age squared
    assert math.isnan(x[0, 3]) and math.isnan(x[0, 5])  # unknown stays unknown
    assert x[0, 6] == GROUPS.index("ST")


def test_informative_columns_need_two_known_values() -> None:
    nan = math.nan
    x = np.array([[1.0, nan, 5.0, 2.0], [2.0, nan, 5.0, nan], [1.0, nan, nan, 3.0]])
    assert informative_columns(x) == (0, 3)  # all-missing and constant columns drop


def test_age_buckets_and_baseline_fallbacks() -> None:
    edges = [21, 24, 27, 30]
    assert [age_bucket(a, edges) for a in (19, 21, 22, 30, 31)] == [0, 0, 1, 3, 4]
    assert age_bucket(None, edges) is None
    train = pd.DataFrame(
        [("CB", 23.0, 1.0), ("CB", 23.5, 3.0), ("CB", 29.0, 5.0), ("ST", 25.0, 7.0)],
        columns=["position_group", "age", "log_value"],
    )
    base = Baseline.fit(train, edges)
    query = pd.DataFrame(
        [("CB", 22.0), ("CB", 33.0), ("W", 25.0), ("ST", None)],
        columns=["position_group", "age"],
    )
    # Cell median (CB, 22-24) = 2; no CB 31+ cell -> CB median 3; unknown group -> overall
    # median 4; unknown age -> group median 7.
    assert list(base.predict(query)) == [2.0, 3.0, 4.0, 7.0]


def test_error_metrics_hand_calculated() -> None:
    y = np.array([1.0, 2.0])
    p = np.array([1.0, 2.0 + math.log(1.5)])
    m = error_metrics(y, p)
    assert m["mae_log"] == pytest.approx(math.log(1.5) / 2)
    assert m["median_abs_pct_error"] == pytest.approx(0.25)  # median of 0% and 50%


def test_model_beats_baseline_on_held_out_season() -> None:
    model = train_value_model(synthetic_seasons(), CFG, GROUPS, seed=42)
    assert (model.train_seasons, model.test_season) == (("2022-23", "2023-24"), "2024-25")
    assert (model.n_train, model.n_test) == (440, 220)
    assert model.metrics["model"]["mae_log"] < model.metrics["baseline"]["mae_log"]
    assert model.metrics["improvement"]["mae_log_pct"] > 20
    assert 0.5 < model.band_coverage <= 1.0  # q10-q90 band covers most held-out values
    # Stats nobody has a value for are left out rather than filled in.
    assert "assists_p90" not in model.features and "def_contribution_p90" not in model.features
    assert {"xg_p90", "team_ppg", "position_group"} <= set(model.features)
    meta = metadata(model, {"git_sha": "abc"})
    assert meta["test_season"] == "2024-25" and meta["git_sha"] == "abc"
    assert meta["eval_features"] == model.eval_features


def test_predictions_are_ordered_and_reproducible() -> None:
    frame = synthetic_seasons(seed=1, n=150)
    a = train_value_model(frame, CFG, GROUPS, seed=7).predict(frame.head(20))
    b = train_value_model(frame, CFG, GROUPS, seed=7).predict(frame.head(20))
    pd.testing.assert_frame_equal(a, b)
    assert (a["band_low_eur"] <= a["implied_value_eur"]).all()
    assert (a["implied_value_eur"] <= a["band_high_eur"]).all()


def test_scores_keep_receipts_and_label_against_the_band() -> None:
    frame = synthetic_seasons(seed=2, n=120)
    model = train_value_model(frame, CFG, GROUPS, seed=3)
    rows = frame.head(3).reset_index(drop=True)
    pred = model.predict(rows)
    rows = rows.assign(
        value_eur=[
            pred.loc[0, "band_low_eur"] / 2,
            pred.loc[1, "implied_value_eur"],
            pred.loc[2, "band_high_eur"] * 2,
        ],
        value_date=[date(2026, 9, 1)] * 3,
        value_source=["transfermarkt"] * 3,
    )
    scored = score_players(model, rows)
    assert list(scored["value_label"]) == ["Undervalued", "Fair", "Premium"]
    assert list(scored["value_date"]) == [date(2026, 9, 1)] * 3  # receipt kept
    pd.testing.assert_frame_equal(scored[list(pred.columns)], pred)
    empty = score_players(model, rows.iloc[0:0])
    assert empty.empty and "value_label" in empty.columns
    assert "not a fee prediction" in CAVEAT


def test_band_labels() -> None:
    assert band_label(5e6, 8e6, 12e6) == "Undervalued"
    assert band_label(10e6, 8e6, 12e6) == "Fair"
    assert band_label(8e6, 8e6, 12e6) == "Fair"  # band edges are inside
    assert band_label(15e6, 8e6, 12e6) == "Premium"


def test_needs_two_seasons() -> None:
    one = synthetic_seasons(n=30)
    with pytest.raises(ValueError, match="at least 2 seasons"):
        train_value_model(one[one["season_id"] == "2024-25"], CFG, GROUPS, seed=1)
