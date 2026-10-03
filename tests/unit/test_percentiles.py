import random

import pandas as pd
import pytest

from scout.db.queries import kpi_percentiles
from scout.db.session import make_engine
from scout.features.percentiles import percent_rank, percentiles


def frame(rows: list[tuple[int, str | None, str, float | None, float, bool]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["player_id", "position_group", "kpi", "value", "minutes", "higher_is_better"],
    )


def by_player(df: pd.DataFrame, kpi: str) -> dict[int, float]:
    sub = df[df["kpi"] == kpi]
    return dict(zip(sub["player_id"], sub["percentile"], strict=True))


def test_percent_rank_semantics() -> None:
    s = pd.Series([3.0, 1.0, 2.0, 2.0])
    assert list(percent_rank(s)) == pytest.approx([1.0, 0.0, 1 / 3, 1 / 3])
    assert list(percent_rank(pd.Series([5.0]))) == [0.0]


def test_hand_calculated_percentiles() -> None:
    df = frame(
        [
            (1, "CB", "tackles", 1.0, 900, True),
            (2, "CB", "tackles", 2.0, 900, True),
            (3, "CB", "tackles", 3.0, 900, True),
            (4, "CB", "tackles", 9.0, 200, True),  # below minutes threshold
            (5, "CB", "tackles", None, 900, True),  # missing value
            (1, "CB", "xgc", 1.0, 900, False),  # inverse: lower is better
            (2, "CB", "xgc", 2.0, 900, False),
            (3, "CB", "xgc", 3.0, 900, False),
            (6, "ST", "tackles", 0.5, 900, True),  # alone in its group
        ]
    )
    out = percentiles(df, min_minutes=600)
    cb = out[out["position_group"] == "CB"]
    assert by_player(cb, "tackles") == {1: 0.0, 2: 50.0, 3: 100.0}
    assert by_player(cb, "xgc") == {1: 100.0, 2: 50.0, 3: 0.0}
    assert set(cb.loc[cb["kpi"] == "tackles", "n_peers"]) == {3}
    st = out[out["position_group"] == "ST"].iloc[0]
    assert (st["percentile"], st["n_peers"]) == (0.0, 1)


def test_ties_share_a_percentile() -> None:
    df = frame([(1, "W", "xa", 1.0, 900, True), (2, "W", "xa", 2.0, 900, True),
                (3, "W", "xa", 2.0, 900, True)])  # fmt: skip
    assert by_player(percentiles(df, min_minutes=600), "xa") == {1: 0.0, 2: 50.0, 3: 50.0}


def test_no_eligible_players() -> None:
    out = percentiles(frame([(1, "W", "xa", 1.0, 10, True)]), min_minutes=600)
    assert out.empty and "n_peers" in out.columns


def test_sql_matches_pandas_on_random_data() -> None:
    rng = random.Random(3)
    rows = [
        (
            pid,
            rng.choice(["CB", "FB", "ST", None]),
            kpi,
            rng.choice([None, round(rng.uniform(0, 3), 1)]),
            rng.choice([100, 600, 1500]),
            kpi != "cards",
        )
        for pid in range(1, 120)
        for kpi in ("xg", "cards")
    ]
    df = frame(rows)
    engine = make_engine("sqlite:///:memory:")
    df.to_sql("kpi_values", engine, index=False)
    sql = kpi_percentiles(engine, min_minutes=600).sort_values(
        ["position_group", "kpi", "player_id"]
    )
    twin = percentiles(df, min_minutes=600).sort_values(["position_group", "kpi", "player_id"])
    assert len(sql) == len(twin) > 0
    assert list(sql["player_id"]) == list(twin["player_id"])
    assert list(sql["percentile"]) == pytest.approx(list(twin["percentile"]))
    assert list(sql["n_peers"]) == list(twin["n_peers"])
