"""Hand-calculated checks of the feature materialisation (PRD §8.1-8.6)."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.errors import ConfigError
from scout.features.materialise import _collapse_clubs, compute_features

CFG = load_config(PROJECT_ROOT / "config")
CUR, PREV = "2026-27", "2025-26"
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def totals_row(pid: int, season: str, source: str, minutes: float, **stats: float) -> dict:
    return {"player_id": pid, "season_id": season, "team_id": 10, "source": source,
            "minutes": minutes, "fetched_at": T0, **stats}  # fmt: skip


@pytest.fixture
def features() -> pd.DataFrame:
    totals = pd.DataFrame(
        [
            totals_row(1, CUR, "fpl", 900, xgc_on_pitch=9.0, yellow_cards=2, red_cards=0),
            totals_row(1, PREV, "vaastav", 1800, xgc_on_pitch=36.0, yellow_cards=1, red_cards=0),
            totals_row(2, CUR, "fpl", 600, xgc_on_pitch=3.0, yellow_cards=0, red_cards=0),
        ]
    )
    padj = pd.DataFrame(
        [
            {"player_id": 1, "season_id": CUR, "team_id": 10, "source": "fpl", "matches": 10,
             "unadjusted_matches": 0, "tackles_padj": 20.0, "recoveries_padj": 30.0,
             "cbi_padj": 40.0},
        ]
    )  # fmt: skip
    return compute_features(
        totals,
        padj,
        {1: "CB", 2: "CB", 3: "ST", 4: None},
        current_season=CUR,
        previous_season=PREV,
        catalogue=CFG.kpis,
        method=CFG.settings.methodology,
    )


def pick(df: pd.DataFrame, pid: int, kpi: str, mode: str = "blended") -> pd.Series:
    sel = df[(df["player_id"] == pid) & (df["kpi"] == kpi) & (df["season_mode"] == mode)]
    assert len(sel) == 1
    return sel.iloc[0]


def test_rows_per_player_mode_and_kpi(features: pd.DataFrame) -> None:
    assert set(features["player_id"]) == {1, 2, 3}  # goalkeeper/unknown group skipped
    assert len(features) == 3 * 2 * len(CFG.kpis.kpis)


def test_blend_and_current_modes(features: pd.DataFrame) -> None:
    # Current: 9.0 xGC over 900 min = 0.9 per 90.
    cur = pick(features, 1, "xgc_on_pitch_p90", "current")
    assert cur["value"] == pytest.approx(0.9)
    assert cur["effective_minutes"] == 900
    # Blended: (900*0.9 + 0.5*1800*1.8) / (900 + 900) = 1.35, effective minutes 1800.
    blended = pick(features, 1, "xgc_on_pitch_p90")
    assert blended["value"] == pytest.approx(1.35)
    assert blended["effective_minutes"] == pytest.approx(1800)
    assert blended["raw_p90"] == pytest.approx(0.9)
    assert bool(blended["used_previous_season"])
    assert blended["as_of"] == T0


def test_shrinkage_toward_minutes_weighted_group_mean(features: pd.DataFrame) -> None:
    # Player 2: 3.0 xGC over 600 min = 0.45 per 90.
    # Prior = (1.35*1800 + 0.45*600) / 2400 = 1.125; k = 10.
    prior = (1.35 * 1800 + 0.45 * 600) / 2400
    assert prior == pytest.approx(1.125)
    p1, p2 = pick(features, 1, "xgc_on_pitch_p90"), pick(features, 2, "xgc_on_pitch_p90")
    assert p1["shrunk"] == pytest.approx((20 * 1.35 + 10 * prior) / 30)
    assert p2["shrunk"] == pytest.approx((600 / 90 * 0.45 + 10 * prior) / (600 / 90 + 10))


def test_inverse_kpi_percentiles_and_n_peers(features: pd.DataFrame) -> None:
    p1, p2 = pick(features, 1, "xgc_on_pitch_p90"), pick(features, 2, "xgc_on_pitch_p90")
    assert (p2["percentile"], p1["percentile"]) == (100.0, 0.0)  # less xGC conceded is better
    assert p1["n_peers"] == p2["n_peers"] == 2


def test_missing_data_stays_missing(features: pd.DataFrame) -> None:
    st = pick(features, 3, "npxg_p90")
    assert pd.isna(st["value"]) and pd.isna(st["percentile"])
    assert st["n_peers"] == 0 and st["minutes"] == 0


def test_def_activity_is_possession_adjusted_and_includes_cbi_for_cb(
    features: pd.DataFrame,
) -> None:
    row = pick(features, 1, "def_activity_padj_p90", "current")
    assert row["value"] == pytest.approx((20 + 30 + 40) / 900 * 90)
    assert row["padj_status"] == "adjusted"
    assert bool(row["is_proxy"])
    assert pick(features, 2, "def_activity_padj_p90")["padj_status"] == "unadjusted"


def test_collapse_clubs_sums_movers() -> None:
    frame = pd.DataFrame(
        [
            totals_row(1, CUR, "fpl", 450, xg=1.0, tackles=None),
            {**totals_row(1, CUR, "fpl", 90, xg=0.5, tackles=None), "team_id": 11},
        ]
    )
    merged = _collapse_clubs(frame)[(1, CUR, "fpl")]
    assert merged["minutes"] == 540 and merged["xg"] == pytest.approx(1.5)
    assert merged["tackles"] is None  # never turned into 0


def test_unknown_kpi_in_config_rejected() -> None:
    kpis = CFG.kpis.model_copy(
        update={"kpis": {**CFG.kpis.kpis, "made_up_p90": CFG.kpis.kpis["xa_p90"]}}
    )
    with pytest.raises(ConfigError, match="made_up_p90"):
        compute_features(
            pd.DataFrame(), pd.DataFrame(), {}, current_season=CUR, previous_season=PREV,
            catalogue=kpis, method=CFG.settings.methodology,
        )  # fmt: skip
