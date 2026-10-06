"""Delta-method age curves (PRD §8.10 step 4, US-18), hand-calculated."""

import pandas as pd
import pytest

from scout.ml.age_curves import AgeCurve, AgePoint, age_curve, delta_pairs, harmonic_mean


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Player 1: age 25 at the end of 2024-25, 0.30 -> 0.40 xG per 90.
            {"player_id": 1, "season_id": "2024-25", "age": 25.4, "minutes": 1800, "xg_p90": 0.30},
            {"player_id": 1, "season_id": "2025-26", "age": 26.4, "minutes": 900, "xg_p90": 0.40},
            # Player 2: age 25, 0.20 -> 0.10.
            {"player_id": 2, "season_id": "2024-25", "age": 25.9, "minutes": 1000, "xg_p90": 0.20},
            {"player_id": 2, "season_id": "2025-26", "age": 26.9, "minutes": 1000, "xg_p90": 0.10},
            # Player 3: too few minutes in the first season.
            {"player_id": 3, "season_id": "2024-25", "age": 26.1, "minutes": 800, "xg_p90": 0.5},
            {"player_id": 3, "season_id": "2025-26", "age": 27.1, "minutes": 2000, "xg_p90": 0.1},
            # Player 4: seasons are not consecutive.
            {"player_id": 4, "season_id": "2023-24", "age": 30.0, "minutes": 2000, "xg_p90": 0.2},
            {"player_id": 4, "season_id": "2025-26", "age": 32.0, "minutes": 2000, "xg_p90": 0.1},
            # Player 5: unknown age, and a missing rate.
            {"player_id": 5, "season_id": "2024-25", "age": None, "minutes": 2000, "xg_p90": 0.2},
            {"player_id": 5, "season_id": "2025-26", "age": None, "minutes": 2000, "xg_p90": 0.3},
            {"player_id": 6, "season_id": "2024-25", "age": 25.0, "minutes": 2000, "xg_p90": None},
            {"player_id": 6, "season_id": "2025-26", "age": 26.0, "minutes": 2000, "xg_p90": 0.3},
        ]
    )


def test_harmonic_mean() -> None:
    assert harmonic_mean(1800, 900) == pytest.approx(1200)
    assert harmonic_mean(0, 0) == 0.0


def test_pairs_need_consecutive_seasons_minutes_age_and_rates() -> None:
    pairs = delta_pairs(_rows(), ["xg"], min_minutes=900)
    assert list(pairs["player_id"]) == [1, 2]
    assert list(pairs["age"]) == [25, 25]
    assert list(pairs["delta"]) == pytest.approx([0.10, -0.10])
    assert list(pairs["weight"]) == pytest.approx([1200, 1000])
    assert set(pairs["season_from"]) == {"2024-25"} and set(pairs["season_to"]) == {"2025-26"}


def test_curve_is_a_weighted_mean_with_a_minimum_sample() -> None:
    pairs = delta_pairs(_rows(), ["xg"], min_minutes=900)
    curve = age_curve(pairs, "xg", "xG", min_pairs=2, age_min=24, age_max=27)
    expected = (0.10 * 1200 - 0.10 * 1000) / 2200
    assert curve.points == [
        AgePoint(24, None, None, 0),
        AgePoint(25, pytest.approx(expected), 0.0, 2),  # type: ignore[arg-type]
        AgePoint(26, None, pytest.approx(expected), 0),  # type: ignore[arg-type]
        AgePoint(27, None, None, 0),
    ]
    assert curve.n_pairs == 2 and curve.at(25) == curve.points[1] and curve.at(40) is None
    sparse = age_curve(pairs, "xg", "xG", min_pairs=3, age_min=24, age_max=27)
    assert all(p.delta is None and p.cumulative is None for p in sparse.points)
    assert isinstance(sparse, AgeCurve) and sparse.points[1].n_pairs == 2
