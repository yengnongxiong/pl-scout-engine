"""GMM role archetypes (PRD §8.10 step 1) on synthetic, well-separated clusters."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from scout.ml.roles import auto_labels, fit_roles, role_matrix

KPIS = ["a", "b", "c"]
NAMES = {"a": "A", "b": "B", "c": "C"}


@pytest.fixture
def blobs() -> tuple[pd.DataFrame, dict[int, int]]:
    """Three synthetic archetypes: high a, high b, high c (20 players each)."""
    rng = np.random.default_rng(0)
    rows, truth = [], {}
    for cluster, centre in enumerate(([5, 0, 0], [0, 5, 0], [0, 0, 5])):
        for i in range(20):
            pid = cluster * 100 + i
            truth[pid] = cluster
            for kpi, mu in zip(KPIS, centre, strict=True):
                rows.append((pid, kpi, mu + rng.normal(0, 0.3), 1500.0))
    rows += [(900, k, 1.0, 300.0) for k in KPIS]  # below the minutes threshold
    rows += [(901, "a", 1.0, 1500.0), (901, "b", 1.0, 1500.0)]  # missing KPI c
    frame = pd.DataFrame(rows, columns=["player_id", "kpi", "shrunk", "effective_minutes"])
    return frame, truth


def test_role_matrix_filters_and_standardises(blobs: tuple[pd.DataFrame, dict[int, int]]) -> None:
    frame, truth = blobs
    matrix = role_matrix(frame, KPIS, min_minutes=900)
    assert set(matrix.player_ids) == set(truth)  # 900 (minutes) and 901 (missing) left out
    assert matrix.z.mean(axis=0) == pytest.approx([0, 0, 0], abs=1e-9)
    assert matrix.z.std(axis=0) == pytest.approx([1, 1, 1])


def test_bic_recovers_three_reproducible_roles(blobs: tuple[pd.DataFrame, dict[int, int]]) -> None:
    frame, truth = blobs
    matrix = role_matrix(frame, KPIS, min_minutes=900)
    model = fit_roles(matrix, k_min=2, k_max=5, seed=42, names=NAMES)
    assert model.k == 3 and set(model.bic) == {2, 3, 4, 5}
    predicted = [model.assignments[p] for p in matrix.player_ids]
    assert adjusted_rand_score([truth[p] for p in matrix.player_ids], predicted) == 1.0
    assert model.silhouette is not None and model.silhouette > 0.7
    assert all(ari > 0.99 for ari in model.stability_ari)
    # Each archetype is labelled by its own high KPI first.
    leads = {label.split(",")[0] for label in model.labels.values()}
    assert leads == {"high A", "high B", "high C"}
    again = fit_roles(matrix, k_min=2, k_max=5, seed=42, names=NAMES)
    assert again.assignments == model.assignments and again.bic == model.bic


def test_auto_labels_and_renames() -> None:
    z = np.array([[2.0, 0.0, -1.0], [2.0, 0.0, -1.0], [-2.0, 0.0, 1.0], [-2.0, 0.0, 1.0]])
    groups = np.array([0, 0, 1, 1])
    assert auto_labels(z, groups, KPIS, NAMES) == {0: "high A, low C", 1: "low A, high C"}
    renamed = auto_labels(z, groups, KPIS, NAMES, {"high A, low C": "Runner"})
    assert renamed == {0: "Runner", 1: "low A, high C"}


def test_too_few_players() -> None:
    frame = pd.DataFrame(
        [(1, k, 1.0, 1000.0) for k in KPIS],
        columns=["player_id", "kpi", "shrunk", "effective_minutes"],
    )
    with pytest.raises(ValueError, match="at least 2"):
        fit_roles(role_matrix(frame, KPIS, min_minutes=900), k_min=2, k_max=3, seed=1, names=NAMES)


def test_train_roles_uses_config() -> None:
    from scout.config import PROJECT_ROOT, load_config
    from scout.ml.roles import role_kpis, short_names, train_roles

    base = load_config(PROJECT_ROOT / "config")
    kpis = role_kpis(base.kpis)
    assert "goals_minus_xg_p90" not in kpis  # weight 0 everywhere: shown, not modelled
    assert short_names(base.kpis)["xa_p90"] == "Expected assists"
    ml = base.settings.ml.model_copy(update={"gmm_k_min": 2, "gmm_k_max": 3})
    config = base.model_copy(update={"settings": base.settings.model_copy(update={"ml": ml})})
    rng = np.random.default_rng(1)
    rows = [
        (pid, kpi, (3.0 if (i % 2) == (pid % 2) else 0.0) + rng.normal(0, 0.2), 1200.0)
        for pid in range(40)
        for i, kpi in enumerate(kpis)
    ]
    frame = pd.DataFrame(rows, columns=["player_id", "kpi", "shrunk", "effective_minutes"])
    model = train_roles(frame, config)
    # The configured k range and seed are used...
    assert set(model.bic) == {2, 3} and model.seed == base.settings.ml.seed
    # ...and BIC may split a group, but never mixes the two synthetic archetypes.
    for cluster in set(model.assignments.values()):
        members = {p % 2 for p, c in model.assignments.items() if c == cluster}
        assert len(members) == 1
