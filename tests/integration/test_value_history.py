"""Valuation history and season bounds on a fixture build that includes the datasets export."""

import gzip
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine

from scout.config import PROJECT_ROOT, AppConfig, Settings, load_config
from scout.db.build import build_warehouse
from scout.db.queries import market_value_history, player_season_totals, season_bounds
from scout.db.session import make_engine
from scout.ingest.base import SnapshotStore
from scout.ingest.transfermarkt import DATASETS_PLAYERS, DATASETS_SOURCE, DATASETS_VALUATIONS
from tests.integration.test_build import _seed

CONFIG = load_config(PROJECT_ROOT / "config")
FIX = PROJECT_ROOT / "tests" / "fixtures" / "transfermarkt"


def _min_minutes(n: int) -> AppConfig:
    vm = CONFIG.settings.value_model.model_copy(update={"min_minutes": n})
    return CONFIG.model_copy(
        update={"settings": CONFIG.settings.model_copy(update={"value_model": vm})}
    )


@pytest.fixture
def warehouse(tmp_path: Path) -> Iterator[tuple[Engine, dict[str, pd.DataFrame]]]:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    store = SnapshotStore(settings.data_dir / "raw", clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    for name, fixture in (
        (DATASETS_PLAYERS, "players"),
        (DATASETS_VALUATIONS, "player_valuations"),
    ):
        body = gzip.compress((FIX / f"synthetic_datasets_{fixture}.csv").read_bytes())
        store.write(DATASETS_SOURCE, name, body)
    build_warehouse(settings, CONFIG)
    engine = make_engine(settings.database_url)
    tables = {n: pd.read_sql_table(n, engine) for n in ("fact_market_value", "dim_match")}
    yield engine, tables
    engine.dispose()


def test_history_is_stored_alongside_the_live_value(
    warehouse: tuple[Engine, dict[str, pd.DataFrame]],
) -> None:
    engine, _ = warehouse
    history = market_value_history(engine)
    # Alex: two stale datasets points plus the live value; nothing else has a value.
    by_source = history.groupby("source")["tm_last_updated"].apply(list).to_dict()
    assert by_source == {
        "transfermarkt": [date(2026, 6, 10)],
        "transfermarkt_datasets": [date(2025, 6, 1), date(2026, 5, 20)],
    }
    assert history["player_id"].nunique() == 1
    stale = history[history["source"] == "transfermarkt_datasets"]
    assert stale["is_stale"].astype(bool).all()


def test_history_matches_pandas_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    mv = tables["fact_market_value"]
    twin = mv[mv["value_eur"].notna() & mv["tm_last_updated"].notna()].sort_values(
        ["player_id", "tm_last_updated", "source"]
    )[["player_id", "source", "value_eur", "tm_last_updated", "is_stale", "fetched_at"]]
    sql = market_value_history(engine)
    assert list(sql.columns) == list(twin.columns)
    assert list(sql["value_eur"]) == list(twin["value_eur"])
    assert [str(d) for d in sql["tm_last_updated"]] == [
        str(pd.Timestamp(d).date()) for d in twin["tm_last_updated"]
    ]


def test_season_bounds_match_pandas_twin(warehouse: tuple[Engine, dict[str, pd.DataFrame]]) -> None:
    engine, tables = warehouse
    m = tables["dim_match"].dropna(subset=["kickoff"])
    grouped = m.groupby("season_id")["kickoff"]
    twin = pd.DataFrame(
        {"first_kickoff": grouped.min(), "last_kickoff": grouped.max(), "matches": grouped.size()}
    ).reset_index()
    sql = season_bounds(engine)
    assert list(sql["season_id"]) == list(twin["season_id"])
    assert list(sql["matches"]) == list(twin["matches"])
    for col in ("first_kickoff", "last_kickoff"):
        assert list(sql[col]) == list(pd.to_datetime(twin[col], utc=True))
    assert len(sql) >= 2  # current season (FPL) and last season (vaastav)


def test_training_frame_labels_past_seasons(
    warehouse: tuple[Engine, dict[str, pd.DataFrame]],
) -> None:
    from scout.ml.value_data import training_frame

    engine, _ = warehouse
    frame = training_frame(engine, _min_minutes(0))
    bounds = season_bounds(engine)
    end = bounds.set_index("season_id").loc["2025-26", "last_kickoff"].date()
    # Only Alex has a valuation history; his 2025-26 season ends in August 2025 and the
    # nearest point in the window is the 2025-06-01 stale datasets value.
    assert list(frame["season_id"]) == ["2025-26"] and len(frame) == 1
    alex = frame.iloc[0]
    assert (alex["value_eur"], alex["value_source"]) == (25_000_000, "transfermarkt_datasets")
    assert alex["value_date"] == date(2025, 6, 1)
    assert alex["age"] == pytest.approx((end - date(1998, 3, 14)).days / 365.25)
    assert alex["position_group"] == "CB" and alex["minutes"] > 0
    # The default minutes floor drops a one-match season.
    assert training_frame(engine, CONFIG).empty


def test_scoring_frame_uses_current_value_and_blended_rates(
    warehouse: tuple[Engine, dict[str, pd.DataFrame]],
) -> None:
    from scout.ml.value_data import scoring_frame

    engine, _ = warehouse
    frame = scoring_frame(engine, _min_minutes(0))
    # Only Alex has a Transfermarkt value: the live one beats the stale datasets points.
    assert len(frame) == 1
    alex = frame.iloc[0]
    history = market_value_history(engine)
    live = history[history["source"] == "transfermarkt"].iloc[0]
    assert alex["value_eur"] == live["value_eur"]
    assert (alex["value_source"], alex["value_date"]) == ("transfermarkt", date(2026, 6, 10))
    assert not bool(alex["value_is_stale"])
    assert alex["age"] == pytest.approx((date(2026, 6, 10) - date(1998, 3, 14)).days / 365.25)
    # 180 FPL minutes this season, 90 last season (vaastav) weighted by lambda.
    totals = player_season_totals(engine)
    mine = totals[totals["player_id"] == alex["player_id"]]
    cur, prev = mine[mine["source"] == "fpl"], mine[mine["source"] == "vaastav"]
    assert (cur["minutes"].sum(), prev["minutes"].sum()) == (180, 90)
    assert (cur["xg"].sum(), prev["xg"].sum()) == (pytest.approx(0.05), pytest.approx(0.04))
    lam = CONFIG.settings.methodology.blend_lambda
    weight_prev = lam * min(90, CONFIG.settings.methodology.prev_season_minutes_cap)
    assert alex["effective_minutes"] == pytest.approx(180 + weight_prev)
    assert bool(alex["used_previous_season"])
    expected_xg = (180 * (0.05 * 90 / 180) + weight_prev * (0.04 * 90 / 90)) / (180 + weight_prev)
    assert alex["xg_p90"] == pytest.approx(expected_xg)
    # The default minutes floor (blended) leaves a two-match player unscored.
    assert scoring_frame(engine, CONFIG).empty


def test_train_records_why_models_were_skipped(
    warehouse: tuple[Engine, dict[str, pd.DataFrame]], tmp_path: Path
) -> None:
    from scout.ml.train import save_artefacts, train_all

    engine, _ = warehouse
    result = train_all(engine, _min_minutes(0), trained_at="2026-10-04T00:00:00+00:00", git_sha="x")
    # build_warehouse alone materialises no features, and one labelled season allows no
    # time-based split: nothing is trained on too little data, and the reason is kept.
    assert result.roles is None and "no player features" in str(result.roles_skipped)
    assert result.value is None and "at least 2 seasons" in str(result.value_skipped)
    assert result.scores.empty and result.similarity == []
    assert result.features_as_of is None
    assert save_artefacts(result, tmp_path / "models") == []
