"""`scout train` artefacts and similarity sanity examples (PRD §8.10-8.11)."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from scout.config import PROJECT_ROOT, load_config
from scout.ml.roles import RoleModel, fit_roles, role_matrix
from scout.ml.train import TrainResult, save_artefacts, similarity_examples
from scout.ml.value_model import ValueModel, train_value_model
from tests.unit.test_value_model import CFG, GROUPS, synthetic_seasons

BASE = load_config(PROJECT_ROOT / "config")


def _roles() -> RoleModel:
    rng = np.random.default_rng(0)
    rows = []
    for cluster, centre in enumerate(([5.0, 0.0], [0.0, 5.0])):
        for i in range(15):
            for kpi, mu in zip(("a", "b"), centre, strict=True):
                rows.append((cluster * 100 + i, kpi, mu + rng.normal(0, 0.3), 1500.0))
    frame = pd.DataFrame(rows, columns=["player_id", "kpi", "shrunk", "effective_minutes"])
    matrix = role_matrix(frame, ["a", "b"], min_minutes=900)
    return fit_roles(matrix, k_min=2, k_max=3, seed=1, names={"a": "A", "b": "B"})


def _result(roles: RoleModel | None = None, value: ValueModel | None = None) -> TrainResult:
    return TrainResult(
        trained_at="2026-10-04T02:00:00+00:00",
        git_sha="abc1234",
        features_as_of="2026-09-01 00:00:00",
        roles=roles,
        roles_skipped=None if roles else "too few players",
        value=value,
        value_skipped=None if value else "too few seasons",
        scores=pd.DataFrame(),
        similarity=[],
    )


def test_artefacts_round_trip_with_metadata(tmp_path: Path) -> None:
    frame = synthetic_seasons(n=60)
    value = train_value_model(frame, CFG, GROUPS, seed=5)
    result = _result(roles=_roles(), value=value)
    written = save_artefacts(result, tmp_path / "models")
    assert [p.name for p in written] == [
        "roles.joblib",
        "roles.json",
        "value_model.joblib",
        "value_model.json",
    ]
    assert result.artefacts == written
    roles_meta = json.loads((tmp_path / "models" / "roles.json").read_text())
    assert (roles_meta["git_sha"], roles_meta["seed"]) == ("abc1234", 1)
    assert sum(roles_meta["cluster_sizes"].values()) == roles_meta["n_players"] == 30
    value_meta = json.loads((tmp_path / "models" / "value_model.json").read_text())
    assert value_meta["test_season"] == "2024-25" and value_meta["features"] == value.features
    assert value_meta["features_as_of"] == "2026-09-01 00:00:00"
    assert value_meta["season_mode"] == "blended"
    loaded = joblib.load(tmp_path / "models" / "value_model.joblib")
    pd.testing.assert_frame_equal(loaded.predict(frame.head(5)), value.predict(frame.head(5)))


def test_nothing_is_written_for_skipped_models(tmp_path: Path) -> None:
    assert save_artefacts(_result(), tmp_path / "models") == []
    assert (tmp_path / "models").is_dir()


def test_similarity_examples_start_from_the_busiest_player() -> None:
    def rows(group: str, pid: int, minutes: float, rng: np.random.Generator) -> list[dict]:
        return [
            {"player_id": pid, "position_group": group, "kpi": kpi,
             "shrunk": rng.uniform(0, 1), "percentile": 50.0, "effective_minutes": minutes}
            for kpi in BASE.kpis.position_groups[group].weights
        ]  # fmt: skip

    rng = np.random.default_rng(3)
    data = [r for pid, m in ((1, 2000.0), (2, 1500.0), (3, 900.0), (4, 2500.0), (5, 1000.0))
            for r in rows("ST", pid, m, rng)]  # fmt: skip
    data += rows("CB", 9, 3000.0, rng)  # a lone centre-back has nobody to compare with
    names = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    examples = similarity_examples(pd.DataFrame(data), BASE, names)
    assert [e.position_group for e in examples] == ["ST"]
    example = examples[0]
    assert (example.player_id, example.player_name) == (4, "Four")
    assert len(example.neighbours) == BASE.settings.ml.similarity_examples_k
    assert "Four" not in [name for name, _ in example.neighbours]
    sims = [s for _, s in example.neighbours]
    assert sims == sorted(sims, reverse=True) and all(-1.0 <= s <= 1.0 for s in sims)


def test_store_outputs_replaces_roles_and_value_scores() -> None:
    from datetime import date

    from sqlalchemy import select

    from scout.db.models import Base, DimPlayer, DimSeason, PlayerRole, PlayerValueScore
    from scout.db.session import make_engine, make_session_factory
    from scout.ml.train import store_outputs

    roles = _roles()
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with make_session_factory(engine).begin() as session:
        session.add(DimSeason(season_id="2026-27", is_current=True))
        session.add_all(
            DimPlayer(player_id=pid, canonical_name=f"Synthetic {pid}") for pid in roles.assignments
        )
    scores = pd.DataFrame(
        [
            {
                "player_id": 0, "season_id": "2026-27", "value_eur": 12_000_000,
                "value_source": "transfermarkt", "value_date": date(2026, 9, 1),
                "value_is_stale": False, "implied_value_eur": 20e6, "band_low_eur": 15e6,
                "band_high_eur": 30e6, "value_label": "Undervalued",
            }
        ]
    )  # fmt: skip
    result = _result(roles=roles)
    result.scores = scores
    assert store_outputs(engine, result) == {"player_role": 30, "player_value_score": 1}
    # A second run replaces rows instead of adding to them; untrained models leave none.
    assert store_outputs(engine, result) == {"player_role": 30, "player_value_score": 1}
    with make_session_factory(engine)() as session:
        stored = session.scalars(select(PlayerRole).where(PlayerRole.player_id == 0)).one()
        assert stored.label == roles.labels[roles.assignments[0]]
        assert stored.git_sha == "abc1234" and stored.season_mode == "blended"
        value = session.scalars(select(PlayerValueScore)).one()
        assert (value.value_label, value.tm_last_updated) == ("Undervalued", date(2026, 9, 1))
    assert store_outputs(engine, _result()) == {"player_role": 0, "player_value_score": 0}
    engine.dispose()
