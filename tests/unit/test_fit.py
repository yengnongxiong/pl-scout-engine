"""Hand-calculated checks of the FitScore components (PRD §8.9)."""

import math

import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.engines.fit import (
    age_profile,
    deficit_weights,
    fit_score,
    need_fill,
    reliability,
    style_fit,
    upgrade_gate,
    weighted_percentile,
)

FIT = load_config(PROJECT_ROOT / "config").fit_weights


def test_weighted_percentile_renormalises_over_known_kpis() -> None:
    pcts = {"a": 80.0, "b": None, "c": 20.0, "d": math.nan}
    # (0.5*80 + 0.25*20) / 0.75 = 60; b and d have no percentile, e has weight 0.
    weights = {"a": 0.5, "b": 0.25, "c": 0.25, "d": 0.1, "e": 0.0}
    assert weighted_percentile(pcts, weights) == pytest.approx(60.0)
    assert weighted_percentile({"b": None}, weights) is None


def test_need_fill_weights_by_gap() -> None:
    gaps = {"a": (0.30, 30.0), "b": (0.20, 10.0), "c": (0.50, -5.0), "d": (0.10, None)}
    deficits = deficit_weights(gaps)
    assert deficits == pytest.approx({"a": 9.0, "b": 2.0})  # only shortfalls count
    pcts = {"a": 90.0, "b": 40.0, "c": 0.0}
    # (9*90 + 2*40) / 11 = 890 / 11.
    assert need_fill(pcts, deficits, {"c": 1.0}) == pytest.approx(890 / 11)
    # No shortfall in the group: fall back to the group weights.
    assert need_fill(pcts, {}, {"a": 0.5, "b": 0.5}) == pytest.approx(65.0)


def test_reliability_combines_volume_and_availability() -> None:
    cfg = FIT.reliability  # full 2500 min, weights 0.6 / 0.4, d -> 0.5
    # Volume 1250/2500 = 0.5, available: 100 * (0.6*0.5 + 0.4*1.0) = 70.
    assert reliability(1250, "a", None, cfg) == pytest.approx(70.0)
    # Doubtful with FPL's 75% chance: chance wins over the status default.
    assert reliability(5000, "d", 75, cfg) == pytest.approx(100 * (0.6 + 0.4 * 0.75))
    assert reliability(5000, "i", None, cfg) == pytest.approx(60.0)
    # Unknown status is missing evidence, not unavailability: volume alone.
    assert reliability(1250, None, None, cfg) == pytest.approx(50.0)
    assert reliability(1250, "zz", None, cfg) == pytest.approx(50.0)
    assert reliability(None, None, None, cfg) is None


def test_style_fit_cosine() -> None:
    assert style_fit([1.0, 0.0], [1.0, 0.0]) == pytest.approx(100.0)
    assert style_fit([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(0.0)
    assert style_fit([1.0, 0.0], [0.0, 1.0]) == pytest.approx(50.0)
    # cos = (1*1 + 1*0) / (sqrt(2) * 1) -> 50 * (1 + 1/sqrt(2)).
    assert style_fit([1.0, 1.0, None], [1.0, 0.0, 3.0]) == pytest.approx(50 * (1 + 2**-0.5))
    assert style_fit([1.0, None], [1.0, 2.0]) is None  # one shared dimension
    assert style_fit([0.0, 0.0], [1.0, 2.0]) is None


def test_age_profile_window_and_penalty() -> None:
    assert age_profile(27.5, (26, 30), 15) == 100.0
    assert age_profile(24.0, (26, 30), 15) == pytest.approx(70.0)
    assert age_profile(33.0, (26, 30), 15) == pytest.approx(55.0)
    assert age_profile(40.0, (26, 30), 15) == 0.0
    assert age_profile(None, (26, 30), 15) is None


def test_fit_score_renormalises_missing_components() -> None:
    weights = dict(FIT.components)
    full = fit_score(
        {"need_fill": 80, "role_quality": 60, "reliability": 50, "style_fit": 40,
         "age_profile": 100},
        weights,
    )  # fmt: skip
    # 0.4*80 + 0.25*60 + 0.15*50 + 0.1*40 + 0.1*100 = 68.5
    assert full.total == pytest.approx(68.5)
    partial = fit_score(
        {"need_fill": 80, "role_quality": 60, "reliability": 50, "style_fit": None,
         "age_profile": 100},
        weights,
    )  # fmt: skip
    # Style unknown: (0.4*80 + 0.25*60 + 0.15*50 + 0.1*100) / 0.9.
    assert partial.total == pytest.approx(64.5 / 0.9)
    assert "style_fit" not in partial.weights_used
    assert sum(partial.weights_used.values()) == pytest.approx(1.0)
    assert partial.components["style_fit"] is None
    empty = fit_score({"need_fill": None}, weights)
    assert empty.total is None and empty.weights_used == {}


def test_upgrade_gate() -> None:
    assert upgrade_gate(80, 60, 15) == "upgrade"
    assert upgrade_gate(75, 60, 15) == "upgrade"  # exactly the threshold
    assert upgrade_gate(70, 60, 15) == "sideways"
    assert upgrade_gate(70, None, 15) == "no_incumbent"
    assert upgrade_gate(None, 60, 15) == "insufficient_data"
