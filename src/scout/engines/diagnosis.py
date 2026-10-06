"""Club diagnosis: where is the squad weakest against the benchmark? (PRD §8.8).

Steps 1-3 of the algorithm:

1. **Group score** per club x position group x KPI: the minutes-weighted mean of the
   club's players' percentiles, weighted by current-season minutes *for this club* in
   that group, so a mid-season signing only counts for minutes played here.
2. **Benchmark score**: the same score averaged over the benchmark clubs.
3. **Gap** = benchmark - club per KPI; **need severity** = sum of KPI weight x
   max(0, gap). Only shortfalls count: being better than the benchmark on one KPI does
   not cancel a weakness on another.

Players without a percentile (below the minutes threshold) carry no evidence and are
left out of the mean rather than treated as average or as zero. Team-level KPIs (step 7)
live in ``engines/team_needs.py`` and are attached to the groups responsible for them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import Engine, select

from scout.config import AppConfig, DiagnosisConfig, KpiCatalogue
from scout.db.models import DimSeason, DimTeam
from scout.db.queries import club_players, player_features, standings, team_matches_played
from scout.db.session import make_session_factory
from scout.engines.benchmark import Benchmark, benchmark_clubs
from scout.engines.team_needs import TeamNeed, team_level_needs
from scout.errors import NotFoundError
from scout.features.per90 import MINUTES_PER_MATCH
from scout.ingest.history import previous_seasons
from scout.ingest.transfermarkt import normalise_name


@dataclass(frozen=True)
class KpiGap:
    """Club vs benchmark on one KPI within a position group."""

    kpi: str
    label: str
    weight: float
    club_score: float | None
    benchmark_score: float | None
    gap: float | None
    is_proxy: bool


@dataclass
class GroupAssessment:
    """Need severity for one position group of the club."""

    position_group: str
    severity: float
    gaps: list[KpiGap] = field(default_factory=list)


def group_scores(club_players: pd.DataFrame, percentiles: pd.DataFrame) -> pd.DataFrame:
    """Minutes-weighted mean percentile per club x position group x KPI.

    Args:
        club_players: ``team_id, player_id, position_group, minutes`` (current season,
            minutes earned at that club).
        percentiles: ``player_id, kpi, percentile`` (blended mode).

    Returns:
        ``team_id, position_group, kpi, score, weight_minutes, players``.
    """
    merged = club_players.merge(percentiles, on="player_id", how="inner")
    merged = merged[merged["percentile"].notna() & (merged["minutes"] > 0)]
    merged = merged.assign(weighted=merged["percentile"] * merged["minutes"])
    grouped = merged.groupby(["team_id", "position_group", "kpi"], as_index=False).agg(
        weighted=("weighted", "sum"),
        weight_minutes=("minutes", "sum"),
        players=("player_id", "nunique"),
    )
    grouped["score"] = grouped["weighted"] / grouped["weight_minutes"]
    return grouped.drop(columns=["weighted"])


def assess_groups(
    club_id: int,
    benchmark_ids: Sequence[int],
    scores: pd.DataFrame,
    catalogue: KpiCatalogue,
) -> list[GroupAssessment]:
    """Gaps and need severity per position group, most severe first."""
    lookup: dict[tuple[int, str, str], float] = {
        (int(t), str(g), str(k)): float(s)
        for t, g, k, s in zip(
            scores["team_id"], scores["position_group"], scores["kpi"], scores["score"],
            strict=True,
        )
    }  # fmt: skip
    out: list[GroupAssessment] = []
    for group, cfg in catalogue.position_groups.items():
        assessment = GroupAssessment(position_group=group, severity=0.0)
        for kpi_id, weight in cfg.weights.items():
            club = lookup.get((club_id, group, kpi_id))
            bench_values = [
                v for b in benchmark_ids if (v := lookup.get((b, group, kpi_id))) is not None
            ]
            bench = sum(bench_values) / len(bench_values) if bench_values else None
            gap = bench - club if bench is not None and club is not None else None
            kpi = catalogue.kpis[kpi_id]
            assessment.gaps.append(
                KpiGap(kpi_id, kpi.label, weight, club, bench, gap, kpi.is_proxy)
            )
            if gap is not None and gap > 0:
                assessment.severity += weight * gap
        out.append(assessment)
    return sorted(out, key=lambda a: (-a.severity, a.position_group))


@dataclass(frozen=True)
class WeakLink:
    """A regular starter who rates poorly on an important KPI (PRD §8.8 step 4)."""

    player_id: int
    position_group: str
    kpi: str
    percentile: float
    minutes_share: float


@dataclass(frozen=True)
class RiskFlag:
    """A squad risk in one position group (PRD §8.8 step 5)."""

    position_group: str
    kind: str  # "depth" | "age" | "contract"
    detail: str
    player_id: int | None = None
    value: float | None = None


def group_weights(catalogue: KpiCatalogue, group: str) -> dict[str, float]:
    """KPI weights for ``group`` (empty for groups outside the catalogue, e.g. GK)."""
    for name, cfg in catalogue.position_groups.items():
        if name == group:
            return dict(cfg.weights)
    return {}


def role_scores(
    players: pd.DataFrame, percentiles: pd.DataFrame, catalogue: KpiCatalogue
) -> dict[int, float]:
    """Overall position-weighted percentile per player (RoleQuality, PRD §8.9).

    Weights are renormalised over the KPIs that have a percentile, so a missing KPI
    shrinks the evidence instead of counting as zero.
    """
    group_of = dict(zip(players["player_id"], players["position_group"], strict=True))
    acc: dict[int, tuple[float, float]] = {}
    for pid, kpi, pct in zip(
        percentiles["player_id"], percentiles["kpi"], percentiles["percentile"], strict=True
    ):
        group = group_of.get(pid)
        if group is None or pd.isna(pct):
            continue
        weight = group_weights(catalogue, str(group)).get(str(kpi), 0.0)
        if weight <= 0:
            continue
        total, wsum = acc.get(int(pid), (0.0, 0.0))
        acc[int(pid)] = (total + weight * float(pct), wsum + weight)
    return {pid: total / wsum for pid, (total, wsum) in acc.items() if wsum > 0}


def weak_links(
    players: pd.DataFrame,
    percentiles: pd.DataFrame,
    *,
    available_minutes: float,
    catalogue: KpiCatalogue,
    cfg: DiagnosisConfig,
) -> list[WeakLink]:
    """Players with a big minutes share and a low percentile on a heavy-weight KPI.

    Args:
        players: The club's ``player_id, position_group, minutes`` (this season, here).
        percentiles: ``player_id, kpi, percentile``.
        available_minutes: Minutes the club has played this season (matches x 90).
        catalogue: KPI weights per group.
        cfg: Thresholds (``weak_link_*``).
    """
    if available_minutes <= 0:
        return []
    info = {
        int(p): (str(g), float(m))
        for p, g, m in zip(
            players["player_id"], players["position_group"], players["minutes"], strict=True
        )
    }
    out: list[WeakLink] = []
    for pid, kpi, pct in zip(
        percentiles["player_id"], percentiles["kpi"], percentiles["percentile"], strict=True
    ):
        if int(pid) not in info or pd.isna(pct):
            continue
        group, minutes = info[int(pid)]
        share = minutes / available_minutes
        weight = group_weights(catalogue, group).get(str(kpi), 0.0)
        if (
            share >= cfg.weak_link_min_minutes_share
            and float(pct) < cfg.weak_link_max_percentile
            and weight >= cfg.weak_link_min_kpi_weight
        ):
            out.append(WeakLink(int(pid), group, str(kpi), float(pct), share))
    return sorted(out, key=lambda w: (w.percentile, w.player_id, w.kpi))


DAYS_PER_YEAR = 365.25
DAYS_PER_MONTH = DAYS_PER_YEAR / 12


def _known_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    return None


def risk_flags(
    players: pd.DataFrame,
    roles: dict[int, float],
    *,
    as_of: date,
    cfg: DiagnosisConfig,
) -> list[RiskFlag]:
    """Depth, age and contract risks per position group (PRD §8.8 step 5).

    Args:
        players: The club's ``player_id, position_group, minutes, birth_date,
            contract_expiry`` (dates may be missing; missing dates raise no flag).
        roles: Overall role score per player (``role_scores``).
        as_of: Date ages and contract windows are measured from.
        cfg: Thresholds (``depth_*``, ``age_risk_*``, ``contract_risk_months``).
    """
    out: list[RiskFlag] = []
    for group, grp in players.groupby("position_group", sort=True):
        grp = grp.sort_values(["minutes", "player_id"], ascending=[False, True])
        total = float(grp["minutes"].sum())
        if total <= 0:
            continue
        key_player = int(grp["player_id"].iloc[0])
        key_share = float(grp["minutes"].iloc[0]) / total
        backups = [int(p) for p in grp["player_id"].iloc[1:]]
        if key_share > cfg.depth_single_player_share and not any(
            roles.get(p, 0.0) > cfg.depth_backup_min_percentile for p in backups
        ):
            out.append(
                RiskFlag(
                    str(group), "depth",
                    f"one player has {key_share:.0%} of minutes and no backup rates above "
                    f"the {cfg.depth_backup_min_percentile:.0f}th percentile",
                    key_player, key_share,
                )
            )  # fmt: skip
        aged = [
            ((as_of - dob).days / DAYS_PER_YEAR, float(m))
            for b, m in zip(grp["birth_date"], grp["minutes"], strict=True)
            if (dob := _known_date(b)) is not None and m > 0
        ]
        weight = sum(m for _, m in aged)
        if weight > 0:
            age = sum(a * m for a, m in aged) / weight
            if age >= cfg.age_risk_min_weighted_age:
                out.append(
                    RiskFlag(str(group), "age", f"minutes-weighted age {age:.1f}", None, age)
                )
        expiry = _known_date(grp["contract_expiry"].iloc[0])
        if expiry is not None:
            months = (expiry - as_of).days / DAYS_PER_MONTH
            if months <= cfg.contract_risk_months:
                out.append(
                    RiskFlag(
                        str(group), "contract",
                        f"key player's contract ends {expiry.isoformat()}",
                        key_player, months,
                    )
                )  # fmt: skip
    return out


@dataclass(frozen=True)
class Evidence:
    """One number behind a need, with its receipt (CLAUDE.md rule 3)."""

    player_id: int
    player_name: str
    kpi: str
    raw_p90: float | None
    value: float | None
    percentile: float | None
    n_peers: int
    minutes: float
    source: str
    as_of: str | None
    is_proxy: bool
    padj_status: str | None


@dataclass
class Need:
    """A ranked position-group need with gaps, evidence, weak links and risks.

    ``team_needs`` are the team-level shortfalls this group is responsible for (step 7);
    they give context and do not change ``severity``.
    """

    rank: int
    need_id: str
    position_group: str
    severity: float
    gaps: list[KpiGap]
    evidence: list[Evidence]
    weak_links: list[WeakLink]
    risks: list[RiskFlag]
    team_needs: list[TeamNeed] = field(default_factory=list)


@dataclass
class Diagnosis:
    """Full diagnosis of one club against a benchmark."""

    team_id: int
    team_name: str
    benchmark: str
    benchmark_team_ids: list[int]
    season_mode: str
    needs: list[Need]
    team_needs: list[TeamNeed] = field(default_factory=list)


@dataclass(frozen=True)
class SeasonContext:
    """Current and previous season ids and this season's clubs (id -> name)."""

    current: str
    previous: str
    team_names: dict[int, str]


def season_context(engine: Engine) -> SeasonContext:
    """Read the current season and its clubs from the warehouse.

    Raises:
        NotFoundError: If no season is marked current (``scout build`` has not run).
    """
    with make_session_factory(engine)() as session:
        current = session.scalars(select(DimSeason.season_id).where(DimSeason.is_current)).first()
        if current is None:
            raise NotFoundError("no current season in the warehouse; run `scout build`")
        teams = {
            t.team_id: t.name
            for t in session.scalars(select(DimTeam).where(DimTeam.fpl_code.is_not(None)))
        }
    return SeasonContext(current, previous_seasons(current, 1)[0], teams)


def find_team(engine: Engine, query: str, aliases: Mapping[str, Sequence[str]]) -> DimTeam:
    """Resolve a club by id, name or alias among current FPL clubs.

    Raises:
        NotFoundError: If nothing matches.
    """
    with make_session_factory(engine)() as session:
        teams = list(session.scalars(select(DimTeam).where(DimTeam.fpl_code.is_not(None))))
    if query.isdigit():
        for team in teams:
            if team.team_id == int(query):
                return team
    wanted = normalise_name(query)
    canonical = {
        normalise_name(spelling): normalise_name(name)
        for name, alts in aliases.items()
        for spelling in (name, *alts)
    }
    target = canonical.get(wanted, wanted)
    for team in teams:
        name = normalise_name(team.name)
        if name == wanted or canonical.get(name, name) == target:
            return team
    raise NotFoundError(f"no current club matches {query!r}", details={"query": query})


def diagnose(
    engine: Engine,
    team_id: int,
    config: AppConfig,
    *,
    benchmark: Benchmark | None = None,
    custom: Sequence[int] = (),
    season_mode: str = "blended",
    as_of: date | None = None,
) -> Diagnosis:
    """Diagnose ``team_id`` from the warehouse (PRD §8.8 steps 1-7)."""
    diag_cfg = config.settings.diagnosis
    bench_name: Benchmark = benchmark or diag_cfg.default_benchmark
    with make_session_factory(engine)() as session:
        team = session.get(DimTeam, team_id)
        if team is None:
            raise NotFoundError(f"no club with id {team_id}")
        team_name = team.name
    ctx = season_context(engine)
    current, previous, league = ctx.current, ctx.previous, list(ctx.team_names)
    table = standings(engine, previous)
    bench_ids = benchmark_clubs(
        table,
        bench_name,
        club_id=team_id,
        sizes={str(k): v for k, v in diag_cfg.benchmark_sizes.items()},
        custom=custom,
        league_clubs=league,
    )
    players = club_players(engine)
    features = player_features(engine, season_mode)
    pct = features[["player_id", "kpi", "percentile"]]
    scores = group_scores(players[["team_id", "player_id", "position_group", "minutes"]], pct)
    assessments = assess_groups(team_id, bench_ids, scores, config.kpis)

    mine = players[players["team_id"] == team_id]
    available = team_matches_played(engine).get(team_id, 0) * MINUTES_PER_MATCH
    links = weak_links(mine, pct, available_minutes=available, catalogue=config.kpis, cfg=diag_cfg)
    roles = role_scores(mine, pct, config.kpis)
    flags = risk_flags(mine, roles, as_of=as_of or date.today(), cfg=diag_cfg)
    team_needs = team_level_needs(
        engine,
        team_id,
        bench_ids,
        league,
        config,
        current=current,
        previous=previous if season_mode == "blended" else None,
    )
    names = dict(zip(mine["player_id"], mine["canonical_name"], strict=True))
    minutes_here = dict(zip(mine["player_id"], mine["minutes"], strict=True))

    needs: list[Need] = []
    for rank, a in enumerate(assessments, start=1):
        group_players = set(mine.loc[mine["position_group"] == a.position_group, "player_id"])
        group_kpis = set(group_weights(config.kpis, a.position_group))
        rows = features[
            features["player_id"].isin(group_players) & features["kpi"].isin(group_kpis)
        ]
        evidence = [
            Evidence(
                player_id=int(r["player_id"]),
                player_name=str(names[r["player_id"]]),
                kpi=str(r["kpi"]),
                raw_p90=_opt_float(r["raw_p90"]),
                value=_opt_float(r["value"]),
                percentile=_opt_float(r["percentile"]),
                n_peers=int(r["n_peers"]),
                minutes=float(minutes_here[r["player_id"]]),
                source=str(r["source"]),
                as_of=None if r["as_of"] is None or pd.isna(r["as_of"]) else str(r["as_of"]),
                is_proxy=bool(r["is_proxy"]),
                padj_status=None if pd.isna(r["padj_status"]) else str(r["padj_status"]),
            )
            for r in rows.to_dict(orient="records")
        ]
        needs.append(
            Need(
                rank=rank,
                need_id=f"{team_id}-{a.position_group}",
                position_group=a.position_group,
                severity=a.severity,
                gaps=a.gaps,
                evidence=sorted(evidence, key=lambda e: (-e.minutes, e.player_id, e.kpi)),
                weak_links=[w for w in links if w.position_group == a.position_group],
                risks=[f for f in flags if f.position_group == a.position_group],
                team_needs=[t for t in team_needs if a.position_group in t.responsible_groups],
            )
        )
    return Diagnosis(team_id, team_name, bench_name, bench_ids, season_mode, needs, team_needs)


def _opt_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(str(value)) if not isinstance(value, (int, float)) else float(value)
