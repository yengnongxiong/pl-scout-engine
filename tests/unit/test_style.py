"""Hand-calculated checks of team style vectors (PRD §8.9 StyleFit)."""

import math

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.engines.fit import style_fit
from scout.engines.style import style_vectors
from tests.unit.test_team_needs import totals_row

FEATURES = load_config(PROJECT_ROOT / "config").kpis.style_features
CUR = "2026-27"
Z = math.sqrt(1.5)  # z-score of the outer value of three evenly spaced values


def _row(team: int, source: str, **stats: tuple[float, int]) -> dict:
    row = totals_row(team, CUR, f"2026-09-2{team % 10} 08:00:00", **stats)
    row["source"] = source
    return row


@pytest.fixture
def styles() -> dict:
    totals = pd.DataFrame(
        [
            _row(1, "fotmob", possession=(1.8, 3)),
            _row(2, "fotmob", possession=(1.5, 3)),
            _row(3, "fotmob", possession=(1.2, 3)),
            _row(1, "understat", ppda=(24.0, 3), deep=(30.0, 3)),
            _row(2, "understat", ppda=(30.0, 3), deep=(15.0, 3)),
            _row(3, "understat", ppda=(36.0, 3)),
            _row(99, "understat", ppda=(90.0, 3), deep=(90.0, 3)),  # not in the league
        ]
    )
    return style_vectors(
        totals, FEATURES, [1, 2, 3], current=CUR, previous=None, lam=0.5, prev_minutes_cap=2000
    )


def test_raw_rates_and_directness_proxy(styles: dict) -> None:
    assert styles[1].features == ("possession", "ppda", "deep_per_possession")
    # Possession 1.8 / 3 = 0.6; PPDA 24 / 3 = 8; deep 30 per 270 minutes = 10 per 90,
    # divided by possession 0.6.
    assert styles[1].raw == pytest.approx((0.6, 8.0, 10.0 / 0.6))
    assert styles[3].raw[2] is None  # no deep completions data: no directness value
    assert 99 not in styles


def test_standardised_across_league_clubs(styles: dict) -> None:
    # Possession 0.6 / 0.5 / 0.4: mean 0.5, population sd 0.1 x sqrt(2/3).
    assert styles[1].z[0] == pytest.approx(Z)
    assert styles[2].z[0] == pytest.approx(0.0)
    assert styles[3].z[0] == pytest.approx(-Z)
    assert styles[1].z[1] == pytest.approx(-Z)  # lowest PPDA
    # Directness only for clubs 1 and 2 (16.67 vs 10): z = +1 / -1; club 99 is ignored.
    assert (styles[1].z[2], styles[2].z[2]) == (pytest.approx(1.0), pytest.approx(-1.0))
    assert styles[3].z[2] is None


def test_receipts(styles: dict) -> None:
    assert styles[1].sources == ("fotmob", "understat")
    assert styles[1].as_of == "2026-09-21T08:00:00"


def test_style_fit_between_clubs(styles: dict) -> None:
    # Clubs 1 and 3 are mirror images on the two shared dimensions: cosine -1.
    assert style_fit(styles[1].z, styles[3].z) == pytest.approx(0.0)
    # Club 1 (Z, -Z, 1) vs club 2 (0, 0, -1): cosine = -1 / (2 x 1) -> 25.
    assert style_fit(styles[1].z, styles[2].z) == pytest.approx(25.0)


def test_single_club_cannot_be_standardised() -> None:
    totals = pd.DataFrame([_row(1, "fotmob", possession=(1.8, 3))])
    out = style_vectors(
        totals, FEATURES, [1], current=CUR, previous=None, lam=0.5, prev_minutes_cap=2000
    )
    assert out[1].raw[0] == pytest.approx(0.6)
    assert out[1].z == (None, None, None)
