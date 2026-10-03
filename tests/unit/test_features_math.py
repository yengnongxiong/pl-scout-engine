"""Hand-calculated tests for PRD §8.1-8.4 formulas."""

import pytest

from scout.features.blend import blend
from scout.features.per90 import nineties, per90
from scout.features.possession import adjust_matches, possession_multiplier
from scout.features.shrinkage import shrink

CLIP = {"clip_min": 0.67, "clip_max": 1.5}


@pytest.mark.parametrize(
    ("total", "minutes", "expected"),
    [(3, 270, 1.0), (1, 45, 2.0), (0, 90, 0.0), (None, 90, None), (2, 0, None), (2, None, None)],
)
def test_per90(total: float | None, minutes: float | None, expected: float | None) -> None:
    assert per90(total, minutes) == (pytest.approx(expected) if expected is not None else None)


def test_nineties() -> None:
    assert nineties(180) == 2.0
    assert nineties(-5) == 0.0


def test_blend_hand_calculation() -> None:
    # (450·0.5 + 0.5·min(3000, 2000)·0.3) / (450 + 0.5·2000) = 525 / 1450
    out = blend(0.5, 450, 0.3, 3000, lam=0.5, prev_minutes_cap=2000)
    assert out.rate == pytest.approx(525 / 1450)
    assert out.minutes == pytest.approx(1450)
    assert out.used_previous


def test_blend_with_one_season_only() -> None:
    cur = blend(0.5, 450, None, 3000, lam=0.5, prev_minutes_cap=2000)
    assert (cur.rate, cur.minutes, cur.used_previous) == (0.5, 450, False)
    prev = blend(None, 0, 0.3, 1000, lam=0.5, prev_minutes_cap=2000)
    assert prev.rate == pytest.approx(0.3)
    assert prev.minutes == pytest.approx(500)
    assert prev.used_previous


def test_blend_without_data_is_missing() -> None:
    out = blend(None, 0, None, 0, lam=0.5, prev_minutes_cap=2000)
    assert out.rate is None and out.minutes == 0


def test_blend_lambda_zero_ignores_previous() -> None:
    out = blend(0.5, 450, 0.3, 2000, lam=0.0, prev_minutes_cap=2000)
    assert out.rate == pytest.approx(0.5)
    assert not out.used_previous


def test_shrink_hand_calculation() -> None:
    # n = 180/90 = 2: (2·1.0 + 10·0.4) / (2 + 10) = 0.5
    assert shrink(1.0, 180, 0.4, 10) == pytest.approx(0.5)
    # n = 100: (100 + 4) / 110
    assert shrink(1.0, 9000, 0.4, 10) == pytest.approx(104 / 110)
    # No minutes → the prior.
    assert shrink(1.0, 0, 0.4, 10) == pytest.approx(0.4)


def test_shrink_missing_and_invalid() -> None:
    assert shrink(None, 900, 0.4, 10) is None
    assert shrink(1.0, 900, None, 10) is None
    with pytest.raises(ValueError):
        shrink(1.0, 900, 0.4, 0)


@pytest.mark.parametrize(
    ("opp_share", "expected"),
    [(0.5, 1.0), (0.6, 0.5 / 0.6), (0.4, 1.25), (0.25, 1.5), (0.8, 0.67), (None, None), (0, None)],
)
def test_possession_multiplier(opp_share: float | None, expected: float | None) -> None:
    got = possession_multiplier(opp_share, **CLIP)
    assert got == (pytest.approx(expected) if expected is not None else None)


def test_adjust_matches_flags_missing_possession() -> None:
    # 10·(0.5/0.6) + 6 (unadjusted) + 4·1.25 = 8.333… + 6 + 5
    out = adjust_matches([(10, 0.6), (6, None), (4, 0.4)], **CLIP)
    assert out.total == pytest.approx(10 * 0.5 / 0.6 + 6 + 5)
    assert (out.matches, out.unadjusted_matches) == (3, 1)
    assert not out.fully_adjusted
    assert adjust_matches([(2, 0.5)], **CLIP).fully_adjusted
