import pandas as pd

from scout.config import PROJECT_ROOT, load_config
from scout.transform.positions import understat_position_groups

MAPPING = load_config(PROJECT_ROOT / "config").positions.understat


def _rows(*rows: tuple[int, str | None, int]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"understat_player_id": p, "position": pos, "minutes": m} for p, pos, m in rows]
    )


def test_group_with_most_minutes_wins() -> None:
    frame = _rows((1, "AMR", 80), (1, "AML", 70), (1, "AMC", 120), (1, "Sub", 400))
    # Wide slots add up (W 150) and beat AMC (120); substitute appearances carry no slot.
    assert understat_position_groups(frame, MAPPING) == {1: "W"}


def test_wing_backs_are_fullbacks() -> None:
    # Understat files wing-backs under DML/DMR (Muñoz, Dalot, Walker in live data).
    frame = _rows((2, "DMR", 90), (3, "DML", 90), (4, "DMC", 90))
    assert understat_position_groups(frame, MAPPING) == {2: "FB", 3: "FB", 4: "DM"}


def test_players_with_no_known_slot_are_left_out() -> None:
    frame = _rows((5, "Sub", 30), (6, None, 90), (7, "XYZ", 90), (8, "DC", 0))
    assert understat_position_groups(frame, MAPPING) == {}


def test_ties_are_broken_deterministically() -> None:
    frame = _rows((9, "DC", 90), (9, "DL", 90))
    assert understat_position_groups(frame, MAPPING) == {9: "CB"}  # alphabetical group
