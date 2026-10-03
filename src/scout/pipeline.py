"""Top-level orchestration across layers (used by the CLI).

``db.build`` may not import ``features`` (layer order, CLAUDE.md), so the full build that
also materialises features lives here, above every layer.
"""

from __future__ import annotations

from scout.config import AppConfig, Settings
from scout.db.build import BuildReport, build_warehouse
from scout.db.session import make_engine
from scout.features.materialise import materialise_features


def build_all(settings: Settings, config: AppConfig, *, allow_invalid: bool = False) -> BuildReport:
    """Build the warehouse, then materialise ``player_season_features``."""
    report = build_warehouse(settings, config, allow_invalid=allow_invalid)
    engine = make_engine(settings.database_url)
    try:
        report.written["player_season_features"] = materialise_features(engine, config)
    finally:
        engine.dispose()
    return report
