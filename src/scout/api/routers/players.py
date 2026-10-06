"""Players: search, profile, similar players and scouting reports (PRD §12)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from scout.api.deps import ApiState, State
from scout.api.errors import ERROR_RESPONSES
from scout.api.schemas import (
    BenchmarkName,
    PlayerAgeCurveResponse,
    PlayerSearchHit,
    ProjectionOut,
    ReportOut,
    ReportResponse,
    SeasonMode,
    SimilarPlayerOut,
    SimilarResponse,
)
from scout.api.shared import age_curves, player_names
from scout.db.queries import player_profiles
from scout.engines.search import SearchIndex
from scout.errors import ConfigError, InvalidRequestError, NotFoundError
from scout.ml.age_curves import project_player
from scout.ml.similarity import find_similar
from scout.reports.facts import FactSheet, build_fact_sheet
from scout.reports.generate import generate_report

router = APIRouter(prefix="/players", tags=["players"], responses=ERROR_RESPONSES)


def _profiles(state: ApiState) -> dict[int, tuple[str, int, str | None]]:
    """Current players: id -> (name, current club id, position group)."""
    state.season()

    def load() -> dict[int, tuple[str, int, str | None]]:
        frame = player_profiles(state.engine)
        return {
            int(p): (str(n), int(t), None if g is None else str(g))
            for p, n, t, g in zip(
                frame["player_id"], frame["canonical_name"], frame["current_team_id"],
                frame["position_group"], strict=True,
            )
        }  # fmt: skip

    return state.cached(("profiles",), load)


@router.get("/search", response_model=list[PlayerSearchHit])
def search_players(
    state: State,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Player name.")],
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> list[PlayerSearchHit]:
    """Prefix search over this season's players (any word of the name), fuzzy for typos."""
    api = state.config.settings.api
    profiles = _profiles(state)
    teams = state.season().team_names
    index = state.cached(
        ("player_index",),
        lambda: SearchIndex([(pid, name, []) for pid, (name, _, _) in profiles.items()]),
    )
    hits = index.search(
        q, limit=min(limit or api.search_limit, api.search_max_limit), fuzzy_cutoff=api.fuzzy_cutoff
    )
    out: list[PlayerSearchHit] = []
    for h in hits:
        _, team, group = profiles[h.id]
        out.append(
            PlayerSearchHit(
                player_id=h.id,
                name=h.label,
                team_id=team,
                team_name=teams.get(team, str(team)),
                position_group=group,
                matched=h.matched,
                kind=h.kind,
                score=h.score,
            )
        )
    return out


def fact_sheet(
    state: ApiState,
    player_id: int,
    *,
    team_id: int | None = None,
    season_mode: str = "blended",
    benchmark: str | None = None,
) -> FactSheet:
    """Cached fact sheet (raises NotFoundError for unknown players or clubs)."""
    state.season()

    def compute() -> FactSheet:
        try:
            return build_fact_sheet(
                state.engine, player_id, state.config, team_id=team_id,
                season_mode=season_mode, benchmark=benchmark,  # type: ignore[arg-type]
            )  # fmt: skip
        except ConfigError as exc:
            raise InvalidRequestError(exc.message) from exc

    return state.cached(("facts", player_id, team_id, season_mode, benchmark), compute)


@router.get("/{player_id}", response_model=FactSheet)
def player_profile(
    state: State,
    player_id: int,
    season_mode: SeasonMode = "blended",
) -> FactSheet:
    """Player profile: header facts, percentiles vs position peers, value, role, caveats.

    Every KPI carries its source and as-of; the Transfermarkt estimated market value
    carries Transfermarkt's own date.
    """
    return fact_sheet(state, player_id, season_mode=season_mode)


@router.get("/{player_id}/similar", response_model=SimilarResponse)
def similar_players(
    state: State,
    player_id: int,
    k: Annotated[int | None, Query(ge=1, le=100)] = None,
    season_mode: SeasonMode = "blended",
) -> SimilarResponse:
    """Top-k most similar players in the same position group (cosine, US-09)."""
    api = state.config.settings.api
    profiles = _profiles(state)
    if player_id not in profiles:
        raise NotFoundError(
            f"no current player with id {player_id}", details={"player_id": player_id}
        )
    name, _, group = profiles[player_id]
    size = min(k or api.similar_k, api.similar_max_k)
    hits = state.cached(
        ("similar", player_id, size, season_mode),
        lambda: find_similar(
            state.engine, player_id, state.config, k=size, season_mode=season_mode
        ),
    )
    teams = state.season().team_names
    names = player_names(state)
    results: list[SimilarPlayerOut] = []
    for hit in hits:
        profile = profiles.get(hit.player_id)
        team = profile[1] if profile else None
        results.append(
            SimilarPlayerOut(
                player_id=hit.player_id,
                player_name=names.get(hit.player_id, str(hit.player_id)),
                team_id=team,
                team_name=teams.get(team) if team is not None else None,
                similarity=hit.similarity,
            )
        )
    return SimilarResponse(
        player_id=player_id,
        player_name=name,
        position_group=group or "",
        season_mode=season_mode,
        results=results,
    )


@router.get("/{player_id}/report", response_model=ReportResponse)
def player_report(
    state: State,
    player_id: int,
    team_id: Annotated[
        int | None, Query(description="Club whose need the report addresses.")
    ] = None,
    season_mode: SeasonMode = "blended",
    benchmark: BenchmarkName | None = None,
) -> ReportResponse:
    """Grounded scouting report (template, or a validated local-LLM rewrite) and its facts."""
    if benchmark == "custom":
        raise InvalidRequestError("reports support the top6, top4 and league benchmarks")
    sheet = fact_sheet(
        state, player_id, team_id=team_id, season_mode=season_mode, benchmark=benchmark
    )
    report = state.cached(
        ("report", player_id, team_id, season_mode, benchmark, state.settings.report_engine),
        lambda: generate_report(sheet, state.settings, state.config),
    )
    return ReportResponse(
        report=ReportOut(
            text=report.text,
            engine=report.engine,
            requested_engine=report.requested_engine,
            fallback_reason=report.fallback_reason,
            violations=list(report.violations),
        ),
        facts=sheet,
    )


@router.get("/{player_id}/age-curve", response_model=PlayerAgeCurveResponse)
def player_age_curve(player_id: int, state: State) -> PlayerAgeCurveResponse:
    """Next-season projection from the age curves: blended rate + typical change at age."""
    curves = age_curves(state)
    result = state.cached(
        ("age_projection", player_id),
        lambda: project_player(state.engine, player_id, state.config, curves),
    )
    return PlayerAgeCurveResponse(
        player_id=player_id,
        age=result.age,
        effective_minutes=result.effective_minutes,
        seasons=curves.seasons,
        caveat=curves.caveat,
        projections=[
            ProjectionOut(
                metric=p.metric,
                label=p.label,
                current=p.current,
                delta=p.delta,
                projected=p.projected,
                n_pairs=p.n_pairs,
            )
            for p in result.projections
        ],
    )
