"""Shortlists: Premier League players who fix a club's need (PRD §8.9).

For one need (a position group of the diagnosed club) the candidate pool is every PL
player in that group at another club, minus the hard filters (budget, age, minutes,
availability, excluded clubs). Each candidate gets a FitScore with its full component
breakdown (``engines.fit``) and an upgrade-gate verdict against the incumbent, the club's
minutes leader in the group. Candidates that fail the gate ("sideways moves") are hidden
by default. The best ``limit`` are picked with the heap top-k (``dsa.heap_topk``).

Every number on a candidate carries a receipt: KPI evidence with source and as-of, the
FPL status snapshot time, and the Transfermarkt estimated market value with
Transfermarkt's own as-of date and the source it came from (CLAUDE.md rules 3 and 10).
Players dropped by a filter are counted per reason so the shortlist can say why it is
short.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import Engine

from scout.config import AppConfig
from scout.db.queries import club_players, latest_market_values, player_features, player_profiles
from scout.dsa.heap_topk import top_k
from scout.engines.benchmark import Benchmark
from scout.engines.diagnosis import (
    DAYS_PER_YEAR,
    Evidence,
    diagnose,
    group_weights,
    season_context,
)
from scout.engines.fit import (
    FitBreakdown,
    GateResult,
    age_profile,
    deficit_weights,
    fit_score,
    need_fill,
    reliability,
    style_fit,
    upgrade_gate,
    weighted_percentile,
)
from scout.engines.style import team_styles
from scout.errors import NotFoundError

HIDDEN_GATES: frozenset[GateResult] = frozenset({"sideways", "insufficient_data"})


@dataclass(frozen=True)
class Filters:
    """Hard filters for the candidate pool (PRD §8.9, US-05)."""

    max_value_eur: int | None = None
    min_age: float | None = None
    max_age: float | None = None
    min_minutes: float | None = None
    exclude_team_ids: tuple[int, ...] = ()
    include_sideways: bool | None = None
    limit: int | None = None


@dataclass(frozen=True)
class MarketValue:
    """A Transfermarkt estimated market value with its receipt."""

    value_eur: int
    tm_last_updated: date
    source: str
    is_stale: bool
    fetched_at: str


@dataclass(frozen=True)
class Incumbent:
    """The club's minutes leader in the need's group (the bar for the upgrade gate)."""

    player_id: int
    player_name: str
    minutes: float
    need_fill: float | None


@dataclass(frozen=True)
class Candidate:
    """One shortlisted player with the full FitScore breakdown and receipts."""

    rank: int
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    position_group: str
    age: float | None
    minutes: float
    effective_minutes: float | None
    fpl_status: str | None
    chance_of_playing: float | None
    status_as_of: str | None
    market_value: MarketValue | None
    fit: FitBreakdown
    gate: GateResult
    evidence: list[Evidence]


@dataclass
class Shortlist:
    """Ranked candidates for one need, plus what was filtered out and why."""

    team_id: int
    team_name: str
    need_id: str
    position_group: str
    season_mode: str
    deficit_weights: dict[str, float]
    incumbent: Incumbent | None
    candidates: list[Candidate]
    excluded: dict[str, int] = field(default_factory=dict)


def preferred_market_value(
    rows: Iterable[Mapping[Hashable, Any]], precedence: Sequence[str]
) -> MarketValue | None:
    """The valuation from the most preferred source that has one (config precedence)."""
    by_source = {str(r["source"]): r for r in rows}
    for source in precedence:
        row = by_source.get(source)
        if row is not None:
            return MarketValue(
                value_eur=int(row["value_eur"]),
                tm_last_updated=row["tm_last_updated"],
                source=source,
                is_stale=bool(row["is_stale"]),
                fetched_at=str(row["fetched_at"]),
            )
    return None


def age_on(birth_date: object, as_of: date) -> float | None:
    """Age in years on ``as_of``; ``None`` when the date of birth is unknown."""
    if not isinstance(birth_date, date):
        return None
    return (as_of - birth_date).days / DAYS_PER_YEAR


def _opt(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(str(value))


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _filter_reason(
    profile: Mapping[Hashable, Any],
    *,
    age: float | None,
    minutes: float | None,
    value: MarketValue | None,
    filters: Filters,
    excluded_statuses: Sequence[str],
) -> str | None:
    """Why a candidate fails a hard filter, or ``None`` if it passes."""
    if _text(profile["fpl_status"]) in excluded_statuses:
        return "unavailable"
    if int(profile["current_team_id"]) in filters.exclude_team_ids:
        return "excluded club"
    if filters.min_age is not None or filters.max_age is not None:
        if age is None:
            return "age unknown"
        if (filters.min_age is not None and age < filters.min_age) or (
            filters.max_age is not None and age > filters.max_age
        ):
            return "outside age range"
    if filters.min_minutes is not None and (minutes or 0.0) < filters.min_minutes:
        return "too few minutes"
    if filters.max_value_eur is not None:
        if value is None:
            return "no market value"
        if value.value_eur > filters.max_value_eur:
            return "over budget"
    return None


def recommend(
    engine: Engine,
    team_id: int,
    config: AppConfig,
    *,
    position_group: str | None = None,
    filters: Filters | None = None,
    benchmark: Benchmark | None = None,
    season_mode: str = "blended",
    as_of: date | None = None,
) -> Shortlist:
    """Shortlist for one of ``team_id``'s needs (the top-ranked need by default).

    Raises:
        NotFoundError: If the club or the requested position group has no need.
    """
    filters = filters or Filters()
    rec_cfg = config.settings.recommend
    fit_cfg = config.fit_weights
    today = as_of or date.today()
    diagnosis = diagnose(
        engine, team_id, config, benchmark=benchmark, season_mode=season_mode, as_of=today
    )
    if not diagnosis.needs:
        raise NotFoundError(f"no needs for club {team_id}")
    group = position_group or diagnosis.needs[0].position_group
    need = next((n for n in diagnosis.needs if n.position_group == group), None)
    if need is None:
        raise NotFoundError(f"no {group} need for club {team_id}", details={"group": group})
    deficits = deficit_weights({g.kpi: (g.weight, g.gap) for g in need.gaps})
    weights = group_weights(config.kpis, group)
    window = next((w for g, w in fit_cfg.peak_age.items() if g == group), None)
    component_weights = {str(name): w for name, w in fit_cfg.components.items()}

    features = player_features(engine, season_mode)
    features = features[features["kpi"].isin(list(weights))]
    pcts: dict[int, dict[str, float | None]] = {}
    eff_minutes: dict[int, float] = {}
    rows_by_player: dict[int, list[dict[Hashable, Any]]] = {}
    for r in features.to_dict(orient="records"):
        pid = int(r["player_id"])
        pcts.setdefault(pid, {})[str(r["kpi"])] = _opt(r["percentile"])
        eff = _opt(r["effective_minutes"]) or 0.0
        eff_minutes[pid] = max(eff_minutes.get(pid, 0.0), eff)
        rows_by_player.setdefault(pid, []).append(r)

    ctx = season_context(engine)
    styles = team_styles(
        engine,
        config,
        list(ctx.team_names),
        current=ctx.current,
        previous=ctx.previous if season_mode == "blended" else None,
    )
    club_style = styles.get(team_id)

    squad = club_players(engine)
    squad = squad[(squad["team_id"] == team_id) & (squad["position_group"] == group)]
    incumbent: Incumbent | None = None
    if not squad.empty:
        lead = squad.sort_values(["minutes", "player_id"], ascending=[False, True]).iloc[0]
        lead_id = int(lead["player_id"])
        incumbent = Incumbent(
            lead_id,
            str(lead["canonical_name"]),
            float(lead["minutes"]),
            need_fill(pcts.get(lead_id, {}), deficits, weights),
        )

    values: dict[int, list[dict[Hashable, Any]]] = {}
    for r in latest_market_values(engine).to_dict(orient="records"):
        values.setdefault(int(r["player_id"]), []).append(r)

    include_sideways = (
        filters.include_sideways
        if filters.include_sideways is not None
        else not rec_cfg.hide_sideways_by_default
    )
    excluded: Counter[str] = Counter()
    pool: list[Candidate] = []
    profiles = player_profiles(engine)
    for p in profiles.to_dict(orient="records"):
        pid, club = int(p["player_id"]), int(p["current_team_id"])
        if p["position_group"] != group or club == team_id:
            continue
        age = age_on(p["birth_date"], today)
        minutes = eff_minutes.get(pid)
        value = preferred_market_value(values.get(pid, []), rec_cfg.market_value_precedence)
        reason = _filter_reason(
            p,
            age=age,
            minutes=minutes,
            value=value,
            filters=filters,
            excluded_statuses=rec_cfg.excluded_statuses,
        )
        if reason is not None:
            excluded[reason] += 1
            continue
        player_pcts = pcts.get(pid, {})
        nf = need_fill(player_pcts, deficits, weights)
        components = {
            "need_fill": nf,
            "role_quality": weighted_percentile(player_pcts, weights),
            "reliability": reliability(
                minutes, _text(p["fpl_status"]), _opt(p["chance_of_playing"]), fit_cfg.reliability
            ),
            "style_fit": style_fit(styles[club].z, club_style.z)
            if club in styles and club_style is not None
            else None,
            "age_profile": age_profile(age, window, fit_cfg.age_profile.penalty_per_year)
            if window is not None
            else None,
        }
        fit = fit_score(components, component_weights)
        if fit.total is None:
            excluded["no evidence"] += 1
            continue
        gate = upgrade_gate(nf, incumbent.need_fill if incumbent else None,
                            fit_cfg.upgrade_gate_min_delta)  # fmt: skip
        if gate in HIDDEN_GATES and not include_sideways:
            excluded["sideways move"] += 1
            continue
        pool.append(
            Candidate(
                rank=0,
                player_id=pid,
                player_name=str(p["canonical_name"]),
                team_id=club,
                team_name=ctx.team_names.get(club, str(club)),
                position_group=group,
                age=age,
                minutes=float(p["season_minutes"] or 0.0),
                effective_minutes=minutes,
                fpl_status=_text(p["fpl_status"]),
                chance_of_playing=_opt(p["chance_of_playing"]),
                status_as_of=_text(p["status_as_of"]),
                market_value=value,
                fit=fit,
                gate=gate,
                evidence=_evidence(rows_by_player.get(pid, []), str(p["canonical_name"]), p),
            )
        )
    limit = filters.limit or rec_cfg.default_limit
    best = top_k(pool, limit, key=lambda c: c.fit.total or 0.0)
    ranked = [replace(c, rank=rank) for rank, c in enumerate(best, start=1)]
    return Shortlist(
        team_id=team_id,
        team_name=diagnosis.team_name,
        need_id=need.need_id,
        position_group=group,
        season_mode=season_mode,
        deficit_weights=deficits,
        incumbent=incumbent,
        candidates=ranked,
        excluded=dict(sorted(excluded.items())),
    )


def _evidence(
    rows: Sequence[Mapping[Hashable, Any]], name: str, profile: Mapping[Hashable, Any]
) -> list[Evidence]:
    """KPI evidence rows for a candidate, each with source and as-of."""
    out = [
        Evidence(
            player_id=int(r["player_id"]),
            player_name=name,
            kpi=str(r["kpi"]),
            raw_p90=_opt(r["raw_p90"]),
            percentile=_opt(r["percentile"]),
            n_peers=int(r["n_peers"]),
            minutes=float(profile["season_minutes"] or 0.0),
            source=str(r["source"]),
            as_of=_text(r["as_of"]),
            is_proxy=bool(r["is_proxy"]),
            padj_status=_text(r["padj_status"]),
        )
        for r in rows
    ]
    return sorted(out, key=lambda e: e.kpi)
