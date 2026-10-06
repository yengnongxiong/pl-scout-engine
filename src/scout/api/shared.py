"""Lookups several routers share, cached per warehouse version."""

from __future__ import annotations

from sqlalchemy import select

from scout.api.deps import ApiState
from scout.config import AppConfig
from scout.db.models import DimPlayer, PlayerValueScore
from scout.db.session import make_session_factory
from scout.ml.age_curves import AgeCurves, build_curves
from scout.ml.value_model import CAVEAT
from scout.reports.facts import ImpliedValueFact


def kpi_label(config: AppConfig, kpi: str) -> str:
    """Display label of a player KPI (the id itself if unknown)."""
    definition = config.kpis.kpis.get(kpi)
    return definition.label if definition else kpi


def group_caveat(config: AppConfig, group: str) -> str | None:
    """The configured caveat for a position group with limited free metrics (e.g. GK)."""
    cfg = next((c for g, c in config.kpis.position_groups.items() if g == group), None)
    return cfg.caveat if cfg else None


def player_names(state: ApiState) -> dict[int, str]:
    """Player id -> canonical name."""

    def load() -> dict[int, str]:
        with make_session_factory(state.engine)() as session:
            rows = session.execute(select(DimPlayer.player_id, DimPlayer.canonical_name)).all()
        return {int(pid): str(name) for pid, name in rows}

    return state.cached(("player_names",), load)


def implied_values(state: ApiState) -> dict[int, ImpliedValueFact]:
    """This season's stats-implied value bands from the last ``scout train`` (US-11)."""
    season = state.season().current

    def load() -> dict[int, ImpliedValueFact]:
        with make_session_factory(state.engine)() as session:
            rows = session.scalars(
                select(PlayerValueScore).where(PlayerValueScore.season_id == season)
            ).all()
        return {
            r.player_id: ImpliedValueFact(
                implied_value_eur=r.implied_value_eur,
                band_low_eur=r.band_low_eur,
                band_high_eur=r.band_high_eur,
                label=r.value_label,
                trained_at=r.trained_at.isoformat(),
                git_sha=r.git_sha,
                caveat=CAVEAT,
            )
            for r in rows
        }

    return state.cached(("implied_values", season), load)


def age_curves(state: ApiState) -> AgeCurves:
    """Aging curves from the warehouse (NotFoundError without two past seasons)."""
    state.season()
    return state.cached(("age_curves",), lambda: build_curves(state.engine, state.config))
