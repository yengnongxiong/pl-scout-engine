"""Hand-calculated checks of PRD §8.8 steps 4-5."""

from datetime import date

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.engines.diagnosis import risk_flags, role_scores, weak_links

CFG = load_config(PROJECT_ROOT / "config")
CATALOGUE, DIAG = CFG.kpis, CFG.settings.diagnosis
AS_OF = date(2026, 10, 1)

PLAYERS = pd.DataFrame(
    [
        (1, "CB", 1800, date(1994, 10, 1), date(2027, 6, 30)),
        (2, "CB", 200, date(2004, 10, 1), None),
        (3, "ST", 1500, None, None),
    ],
    columns=["player_id", "position_group", "minutes", "birth_date", "contract_expiry"],
)
PERCENTILES = pd.DataFrame(
    [
        (1, "def_activity_padj_p90", 20.0),  # weight 0.30 -> weak
        (1, "cards_p90", 10.0),  # weight 0.05 -> not important enough
        (1, "xgc_on_pitch_p90", 80.0),
        (2, "def_activity_padj_p90", 10.0),  # only 10% of minutes
        (2, "xgc_on_pitch_p90", 30.0),
        (3, "npxg_p90", 25.0),  # weight 0.40 -> weak
        (3, "shots_p90", 35.0),  # not below 30
    ],
    columns=["player_id", "kpi", "percentile"],
)


def test_weak_links() -> None:
    links = weak_links(PLAYERS, PERCENTILES, available_minutes=2000, catalogue=CATALOGUE, cfg=DIAG)
    assert [(w.player_id, w.kpi) for w in links] == [
        (1, "def_activity_padj_p90"),
        (3, "npxg_p90"),
    ]
    assert links[0].minutes_share == pytest.approx(0.9)
    assert (
        weak_links(PLAYERS, PERCENTILES, available_minutes=0, catalogue=CATALOGUE, cfg=DIAG) == []
    )


def test_role_scores_renormalise_weights() -> None:
    roles = role_scores(PLAYERS, PERCENTILES, CATALOGUE)
    # Player 1: (0.30*20 + 0.05*10 + 0.20*80) / (0.30 + 0.05 + 0.20)
    assert roles[1] == pytest.approx((6 + 0.5 + 16) / 0.55)
    assert roles[2] == pytest.approx((0.30 * 10 + 0.20 * 30) / 0.50)
    assert roles[3] == pytest.approx((0.40 * 25 + 0.20 * 35) / 0.60)


def test_risk_flags_hand_calculated() -> None:
    roles = role_scores(PLAYERS, PERCENTILES, CATALOGUE)
    flags = {
        (f.position_group, f.kind): f for f in risk_flags(PLAYERS, roles, as_of=AS_OF, cfg=DIAG)
    }
    # CB: player 1 has 90% of minutes and the only backup rates 18 (< 40).
    assert flags[("CB", "depth")].player_id == 1
    assert flags[("CB", "depth")].value == pytest.approx(0.9)
    # Minutes-weighted age ~ (32*1800 + 22*200) / 2000 = 31.0.
    assert flags[("CB", "age")].value == pytest.approx(31.0, abs=0.05)
    # Key player's contract ends 2027-06-30: about 9 months away (<= 12).
    assert flags[("CB", "contract")].value == pytest.approx(272 / (365.25 / 12))
    # ST: single player, no backup; unknown dates raise no age/contract flags.
    assert ("ST", "depth") in flags
    assert ("ST", "age") not in flags and ("ST", "contract") not in flags


def test_good_backup_clears_depth_risk() -> None:
    roles = {1: 60.0, 2: 55.0, 3: 50.0}
    flags = risk_flags(PLAYERS, roles, as_of=AS_OF, cfg=DIAG)
    assert ("CB", "depth") not in {(f.position_group, f.kind) for f in flags}
