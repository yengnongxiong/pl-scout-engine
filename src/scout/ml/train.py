"""``scout train``: fit the ML models, save them with metadata, score this season (PRD §8.10).

Artefacts go to ``<data_dir>/models``: ``roles.joblib`` and ``value_model.joblib``, each
with a metadata JSON next to it (data window, features, metrics, seed, git SHA). A model
that cannot be trained on the data at hand (too few players, fewer than two labelled
seasons) is skipped with the reason recorded; it is never trained on made-up rows.

Similarity sanity examples (PRD §8.11): in each position group, the ranked player with
the most effective minutes and their nearest neighbours.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import Engine, select

from scout.config import AppConfig
from scout.db.models import DimPlayer
from scout.db.queries import player_features
from scout.db.session import make_session_factory
from scout.ml.roles import RoleModel, train_roles
from scout.ml.similarity import group_vectors, similar_players
from scout.ml.value_data import scoring_frame, training_frame
from scout.ml.value_model import ValueModel, metadata, score_players, train_value_model

logger = logging.getLogger(__name__)

SEASON_MODE = "blended"
ROLES_NAME = "roles"
VALUE_NAME = "value_model"
MIN_PEERS = 2  # a neighbour needs a second ranked player in the group


@dataclass(frozen=True)
class SimilarityExample:
    """One player and their nearest neighbours in the same position group."""

    player_id: int
    player_name: str
    position_group: str
    neighbours: tuple[tuple[str, float], ...]


@dataclass
class TrainResult:
    """Everything one ``scout train`` run produced, for the artefacts and the evaluation."""

    trained_at: str
    git_sha: str
    features_as_of: str | None
    roles: RoleModel | None
    roles_skipped: str | None
    value: ValueModel | None
    value_skipped: str | None
    scores: pd.DataFrame
    similarity: list[SimilarityExample]
    artefacts: list[Path] = field(default_factory=list)


def _names(engine: Engine) -> dict[int, str]:
    with make_session_factory(engine)() as session:
        rows = session.execute(select(DimPlayer.player_id, DimPlayer.canonical_name)).tuples()
        return {int(pid): str(name) for pid, name in rows}


def similarity_examples(
    features: pd.DataFrame, config: AppConfig, names: dict[int, str]
) -> list[SimilarityExample]:
    """Per group: the ranked player with the most effective minutes and their neighbours."""
    k = config.settings.ml.similarity_examples_k
    method = config.settings.ml.similarity_method
    minutes = features.groupby("player_id")["effective_minutes"].max().to_dict()
    out: list[SimilarityExample] = []
    for group, group_cfg in config.kpis.position_groups.items():
        vectors = group_vectors(features, group, group_cfg.weights)
        if len(vectors.player_ids) < MIN_PEERS:
            continue
        query = max(vectors.player_ids, key=lambda p: (minutes.get(p) or 0.0, -p))
        hits = similar_players(vectors, query, k, method=method)
        out.append(
            SimilarityExample(
                player_id=query,
                player_name=names.get(query, str(query)),
                position_group=group,
                neighbours=tuple(
                    (names.get(h.player_id, str(h.player_id)), h.similarity) for h in hits
                ),
            )
        )
    return out


def train_all(engine: Engine, config: AppConfig, *, trained_at: str, git_sha: str) -> TrainResult:
    """Fit role archetypes and the value model, score this season, build sanity examples."""
    features = player_features(engine, SEASON_MODE)
    known = features["as_of"].dropna() if "as_of" in features else pd.Series(dtype=object)
    features_as_of = str(known.max()) if not known.empty else None

    roles: RoleModel | None = None
    roles_skipped: str | None = None
    if features.empty:
        roles_skipped = "no player features in the warehouse; run `scout build`"
    else:
        try:
            roles = train_roles(features, config)
        except ValueError as exc:
            roles_skipped = str(exc)
    if roles is None:
        logger.warning("role archetypes not trained", extra={"reason": roles_skipped})

    value: ValueModel | None = None
    value_skipped: str | None = None
    scores = pd.DataFrame()
    frame = training_frame(engine, config)
    if frame.empty:
        value_skipped = "no labelled past player-seasons in the warehouse"
    else:
        try:
            value = train_value_model(
                frame,
                config.settings.value_model,
                list(config.kpis.position_groups),
                config.settings.ml.seed,
            )
        except ValueError as exc:
            value_skipped = str(exc)
    if value is None:
        logger.warning("value model not trained", extra={"reason": value_skipped})
    else:
        scores = score_players(value, scoring_frame(engine, config))

    return TrainResult(
        trained_at=trained_at,
        git_sha=git_sha,
        features_as_of=features_as_of,
        roles=roles,
        roles_skipped=roles_skipped,
        value=value,
        value_skipped=value_skipped,
        scores=scores,
        similarity=[] if features.empty else similarity_examples(features, config, _names(engine)),
    )


def roles_metadata(model: RoleModel, extra: dict[str, object]) -> dict[str, object]:
    """JSON-safe description of fitted role archetypes."""
    sizes: dict[str, int] = {}
    for cluster in model.assignments.values():
        sizes[str(cluster)] = sizes.get(str(cluster), 0) + 1
    return {
        "model": "GaussianMixture(covariance_type=diag), k by BIC",
        "k": model.k,
        "seed": model.seed,
        "features": list(model.kpis),
        "bic": {str(k): v for k, v in model.bic.items()},
        "silhouette": model.silhouette,
        "stability_ari": model.stability_ari,
        "labels": {str(c): label for c, label in model.labels.items()},
        "cluster_sizes": sizes,
        "n_players": len(model.assignments),
        **extra,
    }


def save_artefacts(result: TrainResult, models_dir: Path) -> list[Path]:
    """Write each trained model (joblib) and its metadata JSON; return the paths written."""
    models_dir.mkdir(parents=True, exist_ok=True)
    extra: dict[str, object] = {
        "trained_at": result.trained_at,
        "git_sha": result.git_sha,
        "season_mode": SEASON_MODE,
        "features_as_of": result.features_as_of,
    }
    written: list[Path] = []
    models: list[tuple[str, object, dict[str, object]]] = []
    if result.roles is not None:
        models.append((ROLES_NAME, result.roles, roles_metadata(result.roles, extra)))
    if result.value is not None:
        models.append((VALUE_NAME, result.value, metadata(result.value, extra)))
    for name, model, meta in models:
        artefact, meta_path = models_dir / f"{name}.joblib", models_dir / f"{name}.json"
        joblib.dump(model, artefact)
        meta_path.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
        written += [artefact, meta_path]
    result.artefacts = written
    return written
