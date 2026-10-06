"""Candidate vs incumbent: side-by-side percentiles with deltas (US-07)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from scout.api.deps import State
from scout.api.errors import ERROR_RESPONSES
from scout.api.routers.players import fact_sheet
from scout.api.schemas import (
    ComparePlayer,
    CompareResponse,
    CompareRow,
    MarketValueOut,
    SeasonMode,
    TeamRef,
)
from scout.engines.recommend import need_context
from scout.errors import InvalidRequestError, NotFoundError
from scout.reports.facts import FactSheet

router = APIRouter(tags=["compare"], responses=ERROR_RESPONSES)


def _player(sheet: FactSheet) -> ComparePlayer:
    mv = sheet.market_value
    return ComparePlayer(
        player_id=sheet.player_id,
        player_name=sheet.player_name,
        team_id=sheet.team_id,
        team_name=sheet.team_name,
        position_group=sheet.position_group,
        age=sheet.age,
        minutes=sheet.minutes,
        effective_minutes=sheet.effective_minutes,
        market_value=MarketValueOut(
            value_eur=mv.value_eur,
            tm_last_updated=mv.tm_last_updated,
            source=mv.source,
            is_stale=mv.is_stale,
        )
        if mv
        else None,
    )


@router.get("/compare", response_model=CompareResponse)
def compare(
    state: State,
    a: Annotated[int, Query(description="Player id (usually the candidate).")],
    b: Annotated[int, Query(description="Player id (usually the incumbent).")],
    team_id: Annotated[int | None, Query(description="Club whose need marks KPIs.")] = None,
    season_mode: SeasonMode = "blended",
) -> CompareResponse:
    """KPIs of both players' position groups side by side, with percentile deltas."""
    if a == b:
        raise InvalidRequestError("compare two different players")
    sheet_a = fact_sheet(state, a, season_mode=season_mode)
    sheet_b = fact_sheet(state, b, season_mode=season_mode)
    team: TeamRef | None = None
    need: set[str] = set()
    if team_id is not None:
        names = state.season().team_names
        if team_id not in names:
            raise NotFoundError(f"no current club with id {team_id}", details={"team_id": team_id})
        team = TeamRef(team_id=team_id, name=names[team_id])
        ctx = state.cached(
            ("need_context", team_id, sheet_a.position_group, season_mode),
            lambda: need_context(
                state.engine,
                team_id,
                state.config,
                position_group=sheet_a.position_group,
                season_mode=season_mode,
            ),
        )
        need = set(ctx.deficits)
    by_a = {k.kpi: k for k in sheet_a.kpis}
    by_b = {k.kpi: k for k in sheet_b.kpis}
    order = list(dict.fromkeys([*by_a, *by_b]))
    rows: list[CompareRow] = []
    for kpi in order:
        ka, kb = by_a.get(kpi), by_b.get(kpi)
        ref = ka or kb
        assert ref is not None
        pa = ka.percentile if ka else None
        pb = kb.percentile if kb else None
        rows.append(
            CompareRow(
                kpi=kpi,
                label=ref.label,
                is_proxy=ref.is_proxy,
                is_need=kpi in need,
                a=ka,
                b=kb,
                delta=pa - pb if pa is not None and pb is not None else None,
            )
        )
    return CompareResponse(
        season_mode=season_mode, a=_player(sheet_a), b=_player(sheet_b), team=team, rows=rows
    )
