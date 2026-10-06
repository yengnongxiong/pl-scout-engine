"""Top-level orchestration across layers (used by the CLI).

``db.build`` may not import ``features`` (layer order, CLAUDE.md), so the full build that
also materialises features lives here, above every layer, together with the training step
``scout train`` and ``scout demo`` share.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scout.config import AppConfig, Settings
from scout.db.build import BuildReport, build_warehouse
from scout.db.session import make_engine
from scout.features.materialise import materialise_features
from scout.ml.evaluation import render_evaluation
from scout.ml.train import TrainResult, save_artefacts, store_outputs, train_all


def build_all(settings: Settings, config: AppConfig, *, allow_invalid: bool = False) -> BuildReport:
    """Build the warehouse, then materialise ``player_season_features``."""
    report = build_warehouse(settings, config, allow_invalid=allow_invalid)
    engine = make_engine(settings.database_url)
    try:
        report.written["player_season_features"] = materialise_features(engine, config)
    finally:
        engine.dispose()
    return report


@dataclass
class TrainOutcome:
    """What ``scout train`` produced: the run, files written and warehouse rows stored."""

    result: TrainResult
    written: list[Path]
    stored: dict[str, int]


def train_and_store(
    settings: Settings, config: AppConfig, *, evaluation_path: Path, git_sha: str
) -> TrainOutcome:
    """Train the models, save artefacts, store outputs in the warehouse, write the evaluation.

    Raises:
        ScoutError: If the warehouse cannot be read.
        ValueError: If a model fit fails on the data at hand.
    """
    engine = make_engine(settings.database_url)
    try:
        result = train_all(
            engine,
            config,
            trained_at=datetime.now(UTC).isoformat(timespec="seconds"),
            git_sha=git_sha,
        )
        stored = store_outputs(engine, result)
    finally:
        engine.dispose()
    written = save_artefacts(result, settings.data_dir / "models")
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text(render_evaluation(result), encoding="utf-8")
    return TrainOutcome(result=result, written=[*written, evaluation_path], stored=stored)
