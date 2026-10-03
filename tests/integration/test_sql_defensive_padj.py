"""``defensive_padj.sql`` checked against a pandas twin built on the pure multiplier."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.queries import defensive_padj_totals
from scout.db.session import make_engine
from scout.features.possession import EVEN_SHARE, possession_multiplier
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
METHOD = CONFIG.settings.methodology
CLIP = {"clip_min": METHOD.possession_multiplier_min, "clip_max": METHOD.possession_multiplier_max}
KEYS = ["player_id", "season_id", "team_id", "source"]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    build_warehouse(settings, CONFIG)
    eng = make_engine(settings.database_url)
    yield eng
    eng.dispose()


def pandas_twin(engine: Engine) -> pd.DataFrame:
    facts = pd.read_sql_table("fact_player_match", engine)
    matches = pd.read_sql_table("dim_match", engine)
    teams = pd.read_sql_table("fact_team_match", engine)
    poss = teams[(teams["source"] == "fotmob") & teams["possession"].notna()]
    df = facts[facts["source"].isin(["fpl", "vaastav"])].merge(
        matches[["match_id", "season_id", "home_team_id", "away_team_id"]], on="match_id"
    )
    df["opponent"] = df["away_team_id"].where(
        df["team_id"] == df["home_team_id"], df["home_team_id"]
    )
    lookup = {(int(r.match_id), int(r.team_id)): float(r.possession) for r in poss.itertuples()}
    df["mult"] = [
        possession_multiplier(lookup.get((int(m), int(o))), **CLIP)
        for m, o in zip(df["match_id"], df["opponent"], strict=True)
    ]
    df["unadjusted"] = df["mult"].isna().astype(int)
    factor = df["mult"].fillna(1.0)
    for col in ("tackles", "recoveries", "cbi"):
        df[f"{col}_padj"] = df[col] * factor
    grouped = df.groupby(KEYS, sort=True)
    out = grouped.size().rename("matches").to_frame()
    out["unadjusted_matches"] = grouped["unadjusted"].sum()
    for col in ("tackles_padj", "recoveries_padj", "cbi_padj"):
        out[col] = grouped[col].sum(min_count=1)
    return out.reset_index()


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(KEYS).reset_index(drop=True)
    for col in out.columns:
        if col not in ("season_id", "source"):
            out[col] = pd.to_numeric(out[col]).astype(float)
    return out


def test_sql_matches_pandas_twin(engine: Engine) -> None:
    sql = defensive_padj_totals(engine, even_share=EVEN_SHARE, **CLIP)
    pd.testing.assert_frame_equal(
        _numeric(sql), _numeric(pandas_twin(engine)), check_exact=False, rtol=1e-9
    )


def test_hand_calculated_adjustment(engine: Engine) -> None:
    sql = defensive_padj_totals(engine, even_share=EVEN_SHARE, **CLIP)
    last = sql[(sql["season_id"] == "2025-26") & (sql["source"] == "vaastav")]
    # Alex (Synthetic Rovers) faced Fixture Town with 42% possession: 2 tackles x 0.5/0.42.
    alex = last[last["tackles_padj"].notna() & (last["tackles_padj"] > 0)].iloc[0]
    assert alex["tackles_padj"] == pytest.approx(2 * 0.5 / 0.42)
    assert alex["unadjusted_matches"] == 0
    current = sql[sql["season_id"] == "2026-27"]
    # No FotMob data for the current-season fixtures: raw values, flagged unadjusted.
    assert (current["unadjusted_matches"] == current["matches"]).all()
