"""Data-driven role archetypes (PRD §8.10 step 1, US-10).

Listed positions say where a player starts; archetypes say how they play. Outfield
players with enough blended minutes are described by their standardised shrunk per-90
KPIs, and a Gaussian Mixture Model groups them into k roles, with k chosen by BIC in a
configured range. Each cluster is labelled by the KPIs where its mean z-score is most
extreme (for example "high xGBuildup, high recoveries"), and a rename map in config can
replace the automatic label with a scout-friendly name.

Diagnostics (written to ``docs/EVALUATION.md`` by ``scout train``): the BIC curve, the
silhouette score of the chosen model, and stability as the adjusted Rand index between
fits with different seeds. Archetypes complement listed positions and never replace them
(PRD §8.5).

Players missing any KPI are left out rather than imputed (CLAUDE.md rule 2). All fits are
seeded, so results are reproducible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture

from scout.config import AppConfig, KpiCatalogue

LABEL_FEATURES = 2
STABILITY_SEEDS = 3
MIN_SILHOUETTE_CLUSTERS = 2


@dataclass(frozen=True)
class RoleMatrix:
    """Standardised feature matrix: one row per player, one column per KPI."""

    player_ids: tuple[int, ...]
    kpis: tuple[str, ...]
    z: npt.NDArray[np.float64]
    means: tuple[float, ...]
    sds: tuple[float, ...]


@dataclass
class RoleModel:
    """A fitted archetype model with its diagnostics."""

    k: int
    seed: int
    kpis: tuple[str, ...]
    bic: dict[int, float]
    silhouette: float | None
    stability_ari: list[float]
    labels: dict[int, str]
    assignments: dict[int, int]
    model: GaussianMixture = field(repr=False)


def role_matrix(features: pd.DataFrame, kpis: Sequence[str], *, min_minutes: float) -> RoleMatrix:
    """Players with ``effective_minutes >= min_minutes`` and a shrunk value for every KPI.

    Args:
        features: ``player_id, kpi, shrunk, effective_minutes`` rows (one season mode).
        kpis: KPI ids forming the feature vector.
        min_minutes: Minutes threshold (config ``roles_min_minutes``, PRD §8.10).
    """
    rows = features[features["kpi"].isin(list(kpis)) & features["shrunk"].notna()]
    minutes = rows.groupby("player_id")["effective_minutes"].max()
    wide = rows.pivot_table(index="player_id", columns="kpi", values="shrunk", aggfunc="first")
    wide = wide.reindex(columns=list(kpis)).dropna()
    wide = wide[minutes.reindex(wide.index).fillna(0.0) >= min_minutes].sort_index()
    values = wide.to_numpy(dtype=float)
    means = values.mean(axis=0) if len(values) else np.zeros(len(kpis))
    sds = values.std(axis=0) if len(values) else np.zeros(len(kpis))
    safe = np.where(sds > 0, sds, 1.0)
    z = (values - means) / safe
    return RoleMatrix(
        player_ids=tuple(int(p) for p in wide.index),
        kpis=tuple(kpis),
        z=z,
        means=tuple(float(m) for m in means),
        sds=tuple(float(s) for s in sds),
    )


def auto_labels(
    z: npt.NDArray[np.float64],
    assignments: npt.NDArray[np.int64],
    kpis: Sequence[str],
    names: Mapping[str, str],
    renames: Mapping[str, str] | None = None,
) -> dict[int, str]:
    """Label each cluster by its most extreme mean z-scores ("high X, low Y").

    Args:
        z: Standardised matrix.
        assignments: Cluster per row.
        kpis: Column KPI ids.
        names: Short display name per KPI id.
        renames: Optional map from automatic label to a chosen name (config).
    """
    labels: dict[int, str] = {}
    for cluster in sorted({int(c) for c in assignments}):
        centre = z[assignments == cluster].mean(axis=0)
        order = sorted(range(len(kpis)), key=lambda i: (-abs(float(centre[i])), kpis[i]))
        parts = [
            f"{'high' if centre[i] >= 0 else 'low'} {names.get(kpis[i], kpis[i])}"
            for i in order[:LABEL_FEATURES]
        ]
        label = ", ".join(parts)
        labels[cluster] = (renames or {}).get(label, label)
    return labels


def fit_roles(
    matrix: RoleMatrix,
    *,
    k_min: int,
    k_max: int,
    seed: int,
    names: Mapping[str, str],
    renames: Mapping[str, str] | None = None,
) -> RoleModel:
    """Fit GMMs for k in [k_min, k_max] (capped by the sample), keep the lowest BIC.

    Raises:
        ValueError: If there are fewer than two players to cluster.
    """
    n = len(matrix.player_ids)
    if n < MIN_SILHOUETTE_CLUSTERS:
        raise ValueError(f"need at least 2 players to fit roles, got {n}")
    upper = min(k_max, n - 1)
    lower = min(k_min, upper)
    bic: dict[int, float] = {}
    models: dict[int, GaussianMixture] = {}
    for k in range(lower, upper + 1):
        gmm = GaussianMixture(n_components=k, covariance_type="diag", random_state=seed)
        gmm.fit(matrix.z)
        bic[k] = float(gmm.bic(matrix.z))
        models[k] = gmm
    best_k = min(bic, key=lambda k: (bic[k], k))
    best = models[best_k]
    assignments = best.predict(matrix.z)
    distinct = len(set(assignments.tolist()))
    silhouette = (
        float(silhouette_score(matrix.z, assignments))
        if MIN_SILHOUETTE_CLUSTERS <= distinct < n
        else None
    )
    stability = []
    for offset in range(1, STABILITY_SEEDS):
        other = GaussianMixture(
            n_components=best_k, covariance_type="diag", random_state=seed + offset
        )
        stability.append(
            float(adjusted_rand_score(assignments, other.fit(matrix.z).predict(matrix.z)))
        )
    return RoleModel(
        k=best_k,
        seed=seed,
        kpis=matrix.kpis,
        bic=bic,
        silhouette=silhouette,
        stability_ari=stability,
        labels=auto_labels(matrix.z, assignments, matrix.kpis, names, renames),
        assignments={
            pid: int(c) for pid, c in zip(matrix.player_ids, assignments.tolist(), strict=True)
        },
        model=best,
    )


def role_kpis(catalogue: KpiCatalogue, groups: Sequence[str] | None = None) -> list[str]:
    """KPIs with a positive weight in at least one of ``groups`` (the feature vector).

    Args:
        catalogue: KPI catalogue.
        groups: Position groups to cluster (all when ``None``); goalkeepers are left out by
            config because their KPIs mean nothing for outfield players.
    """
    used = {
        k
        for name, g in catalogue.position_groups.items()
        if groups is None or name in groups
        for k, w in g.weights.items()
        if w > 0
    }
    return sorted(used)


def short_names(catalogue: KpiCatalogue) -> dict[str, str]:
    """Display name per KPI for labels: the configured label without its unit suffix."""
    return {kpi: d.label.split(" (")[0] for kpi, d in catalogue.kpis.items()}


def train_roles(features: pd.DataFrame, config: AppConfig) -> RoleModel:
    """Fit role archetypes on blended features with the configured settings."""
    ml = config.settings.ml
    groups = list(ml.role_groups)
    if "position_group" in features:
        features = features[features["position_group"].isin(groups)]
    matrix = role_matrix(
        features,
        role_kpis(config.kpis, groups),
        min_minutes=config.settings.methodology.roles_min_minutes,
    )
    return fit_roles(
        matrix,
        k_min=ml.gmm_k_min,
        k_max=ml.gmm_k_max,
        seed=ml.seed,
        names=short_names(config.kpis),
        renames=ml.role_renames,
    )
