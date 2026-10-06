"""Clubs: list, search, diagnosis and shortlists (PRD §12, US-01 to US-05)."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from scout.api.deps import ApiState, State
from scout.api.errors import ERROR_RESPONSES
from scout.api.schemas import (
    BenchmarkName,
    CandidateOut,
    DeficitOut,
    DiagnosisResponse,
    EvidenceOut,
    FitOut,
    IncumbentOut,
    KpiGapOut,
    MarketValueOut,
    NeedOut,
    RiskOut,
    SeasonMode,
    ShortlistResponse,
    TeamNeedOut,
    TeamOut,
    TeamRef,
    TeamSearchHit,
    WeakLinkOut,
)
from scout.api.shared import group_caveat, implied_values, kpi_label, player_names
from scout.db.models import DimTeam
from scout.db.session import make_session_factory
from scout.engines.diagnosis import Diagnosis, Evidence, diagnose
from scout.engines.recommend import Candidate, Filters, Shortlist, recommend
from scout.engines.search import SearchIndex
from scout.errors import ConfigError, InvalidRequestError, NotFoundError

router = APIRouter(prefix="/teams", tags=["teams"], responses=ERROR_RESPONSES)


def _teams(state: ApiState) -> list[TeamOut]:
    season = state.season()

    def load() -> list[TeamOut]:
        aliases = state.config.team_aliases.aliases
        with make_session_factory(state.engine)() as session:
            rows = session.scalars(
                select(DimTeam).where(DimTeam.team_id.in_(list(season.team_names)))
            ).all()
        out: list[TeamOut] = []
        for team in sorted(rows, key=lambda t: t.name):
            stored: list[str] = json.loads(team.aliases) if team.aliases else []
            names = dict.fromkeys([*aliases.get(team.name, []), *stored])
            names.pop(team.name, None)
            out.append(
                TeamOut(
                    team_id=team.team_id,
                    name=team.name,
                    short_name=team.short_name,
                    aliases=list(names),
                )
            )
        return out

    return state.cached(("teams",), load)


@router.get("", response_model=list[TeamOut])
def list_teams(state: State) -> list[TeamOut]:
    """Clubs in the current season, alphabetically."""
    return _teams(state)


@router.get("/search", response_model=list[TeamSearchHit])
def search_teams(
    state: State,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Name or alias.")],
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> list[TeamSearchHit]:
    """Prefix search over club names and aliases, with fuzzy suggestions for typos."""
    api = state.config.settings.api
    teams = _teams(state)
    index = state.cached(
        ("team_index",),
        lambda: SearchIndex([(t.team_id, t.name, [*t.aliases, t.short_name or ""]) for t in teams]),
    )
    hits = index.search(
        q, limit=min(limit or api.search_limit, api.search_max_limit), fuzzy_cutoff=api.fuzzy_cutoff
    )
    return [
        TeamSearchHit(team_id=h.id, name=h.label, matched=h.matched, kind=h.kind, score=h.score)
        for h in hits
    ]


def _check_team(state: ApiState, team_id: int) -> str:
    names = state.season().team_names
    if team_id not in names:
        raise NotFoundError(f"no current club with id {team_id}", details={"team_id": team_id})
    return names[team_id]


def _check_custom(state: ApiState, benchmark: str | None, custom: list[int]) -> tuple[int, ...]:
    if benchmark != "custom":
        return ()
    if not custom:
        raise InvalidRequestError("benchmark=custom needs at least one `custom` club id")
    unknown = sorted(set(custom) - set(state.season().team_names))
    if unknown:
        raise InvalidRequestError("unknown custom benchmark clubs", details={"team_ids": unknown})
    return tuple(sorted(set(custom)))


def evidence_out(e: Evidence, state: ApiState) -> EvidenceOut:
    """API view of one evidence row (adds the KPI label)."""
    return EvidenceOut(
        player_id=e.player_id,
        player_name=e.player_name,
        kpi=e.kpi,
        label=kpi_label(state.config, e.kpi),
        raw_p90=e.raw_p90,
        value=e.value,
        percentile=e.percentile,
        n_peers=e.n_peers,
        minutes=e.minutes,
        source=e.source,
        as_of=e.as_of,
        is_proxy=e.is_proxy,
        padj_status=e.padj_status,
    )


def _diagnosis_out(result: Diagnosis, state: ApiState) -> DiagnosisResponse:
    season = state.season()
    names = player_names(state)
    needs = [
        NeedOut(
            rank=n.rank,
            need_id=n.need_id,
            position_group=n.position_group,
            severity=n.severity,
            gaps=[
                KpiGapOut(
                    kpi=g.kpi,
                    label=g.label,
                    weight=g.weight,
                    is_proxy=g.is_proxy,
                    club_score=g.club_score,
                    benchmark_score=g.benchmark_score,
                    gap=g.gap,
                )
                for g in n.gaps
            ],
            evidence=[evidence_out(e, state) for e in n.evidence],
            weak_links=[
                WeakLinkOut(
                    player_id=w.player_id,
                    player_name=names.get(w.player_id, str(w.player_id)),
                    kpi=w.kpi,
                    label=kpi_label(state.config, w.kpi),
                    percentile=w.percentile,
                    minutes_share=w.minutes_share,
                )
                for w in n.weak_links
            ],
            risks=[
                RiskOut(
                    kind=r.kind,
                    detail=r.detail,
                    player_id=r.player_id,
                    player_name=names.get(r.player_id) if r.player_id is not None else None,
                    value=r.value,
                )
                for r in n.risks
            ],
            team_needs=[t.kpi for t in n.team_needs],
            caveat=group_caveat(state.config, n.position_group),
        )
        for n in result.needs
    ]
    return DiagnosisResponse(
        team_id=result.team_id,
        team_name=result.team_name,
        season_mode="current" if result.season_mode == "current" else "blended",
        current_season=season.current,
        benchmark=result.benchmark,
        benchmark_teams=[
            TeamRef(team_id=t, name=season.team_names.get(t, str(t)))
            for t in result.benchmark_team_ids
        ],
        needs=needs,
        team_needs=[
            TeamNeedOut(
                kpi=t.kpi,
                label=t.label,
                higher_is_better=t.higher_is_better,
                club_value=t.club_value,
                club_percentile=t.club_percentile,
                benchmark_value=t.benchmark_value,
                benchmark_percentile=t.benchmark_percentile,
                gap=t.gap,
                n_peers=t.n_peers,
                matches=t.matches,
                previous_matches=t.previous_matches,
                responsible_groups=list(t.responsible_groups),
                source=t.source,
                as_of=t.as_of,
            )
            for t in result.team_needs
        ],
    )


@router.get("/{team_id}/diagnosis", response_model=DiagnosisResponse)
def team_diagnosis(
    state: State,
    team_id: int,
    season_mode: SeasonMode = "blended",
    benchmark: BenchmarkName | None = None,
    custom: Annotated[list[int] | None, Query(description="Club ids for benchmark=custom.")] = None,
) -> DiagnosisResponse:
    """Needs, weak links and risks with evidence, every position group ranked (US-02/03)."""
    _check_team(state, team_id)
    custom_ids = _check_custom(state, benchmark, custom or [])

    def compute() -> DiagnosisResponse:
        try:
            result = diagnose(
                state.engine, team_id, state.config,
                benchmark=benchmark, custom=custom_ids, season_mode=season_mode,
            )  # fmt: skip
        except ConfigError as exc:
            raise InvalidRequestError(exc.message) from exc
        return _diagnosis_out(result, state)

    return state.cached(("diagnosis", team_id, season_mode, benchmark, custom_ids), compute)


def candidate_out(c: Candidate, state: ApiState) -> CandidateOut:
    """API view of one shortlisted (or assessed) player."""
    mv = c.market_value
    return CandidateOut(
        rank=c.rank,
        player_id=c.player_id,
        player_name=c.player_name,
        team_id=c.team_id,
        team_name=c.team_name,
        position_group=c.position_group,
        age=c.age,
        minutes=c.minutes,
        effective_minutes=c.effective_minutes,
        fpl_status=c.fpl_status,
        chance_of_playing=c.chance_of_playing,
        status_as_of=c.status_as_of,
        market_value=MarketValueOut(
            value_eur=mv.value_eur,
            tm_last_updated=mv.tm_last_updated,
            source=mv.source,
            is_stale=mv.is_stale,
        )
        if mv
        else None,
        implied_value=implied_values(state).get(c.player_id),
        fit=FitOut(total=c.fit.total, components=c.fit.components, weights_used=c.fit.weights_used),
        gate=c.gate,
        evidence=[evidence_out(e, state) for e in c.evidence],
    )


def _shortlist_out(s: Shortlist, state: ApiState) -> ShortlistResponse:
    inc = s.incumbent
    return ShortlistResponse(
        team_id=s.team_id,
        team_name=s.team_name,
        need_id=s.need_id,
        position_group=s.position_group,
        season_mode="current" if s.season_mode == "current" else "blended",
        deficits=[
            DeficitOut(kpi=k, label=kpi_label(state.config, k), weight=w)
            for k, w in sorted(s.deficit_weights.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        incumbent=IncumbentOut(
            player_id=inc.player_id,
            player_name=inc.player_name,
            minutes=inc.minutes,
            need_fill=inc.need_fill,
        )
        if inc
        else None,
        candidates=[candidate_out(c, state) for c in s.candidates],
        excluded=s.excluded,
        caveat=group_caveat(state.config, s.position_group),
    )


def _need_group(team_id: int, need_id: str | None, position_group: str | None) -> str | None:
    if need_id is None:
        return position_group
    team_part, _, group = need_id.partition("-")
    if team_part != str(team_id) or not group:
        raise InvalidRequestError(
            f"need {need_id!r} does not belong to club {team_id}", details={"need_id": need_id}
        )
    if position_group is not None and position_group != group:
        raise InvalidRequestError("need_id and position_group disagree")
    return group


@router.get("/{team_id}/recommendations", response_model=ShortlistResponse)
def team_recommendations(
    state: State,
    team_id: int,
    need_id: Annotated[str | None, Query(description="Need id from the diagnosis.")] = None,
    position_group: Annotated[str | None, Query(description="Alternative to need_id.")] = None,
    max_value_eur: Annotated[int | None, Query(ge=0)] = None,
    min_age: Annotated[float | None, Query(ge=0, le=60)] = None,
    max_age: Annotated[float | None, Query(ge=0, le=60)] = None,
    min_minutes: Annotated[float | None, Query(ge=0)] = None,
    exclude_team_ids: Annotated[list[int] | None, Query()] = None,
    include_sideways: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    season_mode: SeasonMode = "blended",
    benchmark: BenchmarkName | None = None,
    custom: Annotated[list[int] | None, Query()] = None,
) -> ShortlistResponse:
    """Ranked shortlist for one need with FitScore breakdowns and receipts (US-04/05)."""
    _check_team(state, team_id)
    if min_age is not None and max_age is not None and min_age > max_age:
        raise InvalidRequestError("min_age must not exceed max_age")
    group = _need_group(team_id, need_id, position_group)
    custom_ids = _check_custom(state, benchmark, custom or [])
    filters = Filters(
        max_value_eur=max_value_eur,
        min_age=min_age,
        max_age=max_age,
        min_minutes=min_minutes,
        exclude_team_ids=tuple(sorted(set(exclude_team_ids or []))),
        include_sideways=include_sideways,
        limit=min(limit, state.config.settings.api.max_shortlist) if limit else None,
    )

    def compute() -> ShortlistResponse:
        try:
            shortlist = recommend(
                state.engine, team_id, state.config, position_group=group, filters=filters,
                benchmark=benchmark, custom=custom_ids, season_mode=season_mode,
            )  # fmt: skip
        except ConfigError as exc:
            raise InvalidRequestError(exc.message) from exc
        return _shortlist_out(shortlist, state)

    return state.cached(
        ("recommend", team_id, group, filters, season_mode, benchmark, custom_ids), compute
    )
