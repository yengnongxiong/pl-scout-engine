"""Fact sheets: every number and claim a scouting report may use (PRD §9 step 1).

A report is rendered *from* a fact sheet and validated *against* it, so a number can only
appear in a report if it is in the fact sheet, and every fact-sheet number carries a
receipt (source and as-of, CLAUDE.md rule 3). Missing data stays ``None`` and renders as
"Not available" (rule 2).

The sheet covers PRD §9 step 5: header facts (club, age, position, Transfermarkt estimated
market value with its as-of date, contract), position-group KPIs with percentiles and peer
counts, strengths and concerns by percentile band, the role archetype, comparable players,
the stats-implied value band, and, when a club is given, how the player fits that club's
need compared with the incumbent. Caveats (small sample, proxy metrics, unadjusted
defensive numbers, stale value, no previous PL season) are derived here, not by the
template.
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable, Iterable, Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select

from scout.config import AppConfig, ReportBands
from scout.db.models import DimTeam, PlayerRole, PlayerValueScore
from scout.db.queries import latest_market_values, player_features, player_profiles
from scout.db.session import make_session_factory
from scout.engines.benchmark import Benchmark
from scout.engines.diagnosis import group_weights, season_context
from scout.engines.recommend import (
    Assessment,
    age_on,
    assess_player,
    preferred_market_value,
)
from scout.errors import NotFoundError
from scout.ml.similarity import find_similar
from scout.ml.value_model import CAVEAT as VALUE_CAVEAT

Band = Literal["elite", "strong", "above_average", "below_average", "weak"]
CaveatKind = Literal[
    "small_sample",
    "proxy_metric",
    "unadjusted_defence",
    "stale_value",
    "no_market_value",
    "no_previous_season",
    "value_model",
    "no_comparables",
    "same_club",
]

EUR_PER_MILLION = 1_000_000
PERCENT = 100.0
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class _Fact(BaseModel):
    model_config = ConfigDict(frozen=True)


class MarketValueFact(_Fact):
    """A Transfermarkt estimated market value with Transfermarkt's own as-of date."""

    value_eur: int
    tm_last_updated: date
    source: str = Field(description="override, transfermarkt or transfermarkt_datasets")
    is_stale: bool


class KpiFact(_Fact):
    """One KPI of the player's position group with its receipt."""

    kpi: str
    label: str
    weight: float = Field(description="Weight of the KPI in the position group (0-1).")
    is_proxy: bool
    proxy_for: str | None
    value: float | None = Field(description="Per-90 value in this season mode.")
    raw_p90: float | None = Field(description="This season's per-90 value alone.")
    percentile: float | None
    band: Band | None
    n_peers: int
    source: str
    as_of: str | None
    padj_status: str | None


class RoleFact(_Fact):
    """Role archetype from the last ``scout train`` run (PRD §8.10 step 1)."""

    label: str
    trained_at: str
    git_sha: str


class ComparableFact(_Fact):
    """A similar player in the same position group (PRD §8.10 step 2)."""

    player_id: int
    player_name: str
    team_name: str | None
    similarity: float = Field(description="Cosine similarity, -1 to 1.")


class ImpliedValueFact(_Fact):
    """Stats-implied value band from the value model (PRD §8.10 step 3)."""

    implied_value_eur: float
    band_low_eur: float
    band_high_eur: float
    label: str = Field(description="Undervalued, Fair or Premium.")
    trained_at: str
    git_sha: str
    caveat: str


class NeedKpiFact(_Fact):
    """A KPI where the club trails the benchmark: candidate vs incumbent."""

    kpi: str
    label: str
    is_proxy: bool
    gap: float = Field(description="Benchmark minus club, percentile points.")
    candidate_percentile: float | None
    incumbent_percentile: float | None
    delta: float | None = Field(description="Candidate minus incumbent, percentile points.")


class IncumbentFact(_Fact):
    """The club's minutes leader in the group."""

    player_id: int
    player_name: str
    minutes: float
    need_fill: float | None


class FitFact(_Fact):
    """How the player fits one club's need (PRD §8.9)."""

    team_id: int
    team_name: str
    benchmark: str
    position_group: str
    same_club: bool
    fit_score: float | None
    components: dict[str, float | None]
    weights_used: dict[str, float]
    gate: str
    gate_min_delta: float = Field(description="NeedFill points needed to beat the incumbent.")
    need_fill: float | None
    incumbent: IncumbentFact | None
    need_kpis: list[NeedKpiFact]


class Caveat(_Fact):
    """A data caveat inserted into the report (PRD §9 step 2)."""

    kind: CaveatKind
    text: str


class Receipt(_Fact):
    """A source behind the sheet and the newest timestamp used from it."""

    source: str
    as_of: str | None


class FactSheet(_Fact):
    """Everything a report about one player may state (PRD §9)."""

    player_id: int
    player_name: str
    team_id: int
    team_name: str
    position_group: str
    birth_date: date | None
    age: float | None
    as_of: date = Field(description="Date ages and contract windows are measured from.")
    season_mode: str
    current_season: str
    previous_season: str | None = Field(description="Set when last season is blended in.")
    minutes: float = Field(description="This season's FPL minutes.")
    effective_minutes: float | None = Field(description="Blended minutes behind the rates.")
    fpl_status: str | None
    chance_of_playing: float | None
    status_as_of: str | None
    contract_expiry: date | None
    market_value: MarketValueFact | None
    kpis: list[KpiFact]
    strengths: list[str] = Field(description="KPI ids rated strong or elite.")
    concerns: list[str] = Field(description="KPI ids rated weak.")
    role: RoleFact | None
    comparables: list[ComparableFact]
    implied_value: ImpliedValueFact | None
    fit: FitFact | None
    caveats: list[Caveat]
    sources: list[Receipt]

    def kpi(self, kpi_id: str) -> KpiFact:
        """The KPI fact with id ``kpi_id``."""
        return next(k for k in self.kpis if k.kpi == kpi_id)


def percentile_band(percentile: float | None, bands: ReportBands) -> Band | None:
    """PRD §9 band for a percentile (lower bounds inclusive); ``None`` when unknown."""
    if percentile is None or math.isnan(percentile):
        return None
    if percentile >= bands.elite:
        return "elite"
    if percentile >= bands.strong:
        return "strong"
    if percentile >= bands.above_average:
        return "above_average"
    if percentile >= bands.below_average:
        return "below_average"
    return "weak"


def _opt(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(str(value))


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return str(value)


def _date(value: object) -> date | None:
    return value if isinstance(value, date) else None


def kpi_facts(
    rows: Iterable[Mapping[Hashable, Any]],
    group: str,
    config: AppConfig,
) -> list[KpiFact]:
    """KPI facts for the player's group, heaviest weight first (missing KPIs left out)."""
    weights = group_weights(config.kpis, group)
    by_kpi = {str(r["kpi"]): r for r in rows}
    bands = config.settings.reports.bands
    out: list[KpiFact] = []
    for kpi_id, weight in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        row = by_kpi.get(kpi_id)
        if row is None:
            continue
        definition = config.kpis.kpis[kpi_id]
        pct = _opt(row["percentile"])
        out.append(
            KpiFact(
                kpi=kpi_id,
                label=definition.label,
                weight=weight,
                is_proxy=definition.is_proxy,
                proxy_for=definition.proxy_for,
                value=_opt(row["value"]),
                raw_p90=_opt(row["raw_p90"]),
                percentile=pct,
                band=percentile_band(pct, bands),
                n_peers=int(row["n_peers"]),
                source=str(row["source"]),
                as_of=_text(row["as_of"]),
                padj_status=_text(row["padj_status"]),
            )
        )
    return out


def strengths_and_concerns(kpis: list[KpiFact], max_listed: int) -> tuple[list[str], list[str]]:
    """Weighted KPIs rated strong/elite, and weighted KPIs rated weak.

    Ordered by how far they sit from the middle, weighted by importance, so the most
    telling ones come first; KPIs with zero weight are shown in the table but never
    listed (e.g. finishing luck, PRD §8.7).
    """
    rated = [k for k in kpis if k.percentile is not None and k.weight > 0]
    strong = [k for k in rated if k.band in ("elite", "strong")]
    weak = [k for k in rated if k.band == "weak"]
    strong.sort(key=lambda k: (-(k.weight * ((k.percentile or 0.0) - 50.0)), k.kpi))
    weak.sort(key=lambda k: (-(k.weight * (50.0 - (k.percentile or 0.0))), k.kpi))
    return [k.kpi for k in strong[:max_listed]], [k.kpi for k in weak[:max_listed]]


def fit_fact(assessment: Assessment, config: AppConfig) -> FitFact:
    """Fit of the assessed player for the club's need, with the incumbent comparison."""
    ctx, cand = assessment.context, assessment.candidate
    inc = ctx.incumbent
    mine = ctx.percentiles.get(cand.player_id, {})
    theirs = ctx.percentiles.get(inc.player_id, {}) if inc else {}
    need_kpis: list[NeedKpiFact] = []
    for gap in sorted(ctx.gaps, key=lambda g: (-(g.weight * (g.gap or 0.0)), g.kpi)):
        if gap.kpi not in ctx.deficits or gap.gap is None:
            continue
        a, b = mine.get(gap.kpi), theirs.get(gap.kpi)
        need_kpis.append(
            NeedKpiFact(
                kpi=gap.kpi,
                label=gap.label,
                is_proxy=gap.is_proxy,
                gap=gap.gap,
                candidate_percentile=a,
                incumbent_percentile=b,
                delta=a - b if a is not None and b is not None else None,
            )
        )
    return FitFact(
        team_id=ctx.team_id,
        team_name=ctx.team_name,
        benchmark=ctx.benchmark,
        position_group=ctx.position_group,
        same_club=assessment.same_club,
        fit_score=cand.fit.total,
        components=dict(cand.fit.components),
        weights_used=dict(cand.fit.weights_used),
        gate=cand.gate,
        gate_min_delta=config.fit_weights.upgrade_gate_min_delta,
        need_fill=cand.fit.components.get("need_fill"),
        incumbent=IncumbentFact(
            player_id=inc.player_id,
            player_name=inc.player_name,
            minutes=inc.minutes,
            need_fill=inc.need_fill,
        )
        if inc
        else None,
        need_kpis=need_kpis[: config.settings.reports.max_listed],
    )


def caveats(sheet: dict[str, Any], kpis: list[KpiFact], config: AppConfig) -> list[Caveat]:
    """Caveats for the report, in a fixed order (PRD §9 step 2)."""
    out: list[Caveat] = []
    rep = config.settings.reports
    eff = sheet["effective_minutes"]
    if eff is None or eff < rep.small_sample_minutes:
        shown = "no" if eff is None else f"{eff:.0f}"
        out.append(
            Caveat(
                kind="small_sample",
                text=f"Small sample: {shown} effective minutes behind these rates "
                f"(below {rep.small_sample_minutes:.0f}); rates are shrunk toward the "
                "position-group average.",
            )
        )
    if sheet["season_mode"] == "blended" and sheet["previous_season"] is None:
        out.append(
            Caveat(
                kind="no_previous_season",
                text="No previous Premier League season in the blend: this season's "
                "numbers carry the rates alone.",
            )
        )
    proxies = [k.label for k in kpis if k.is_proxy]
    if proxies:
        out.append(
            Caveat(
                kind="proxy_metric",
                text="Proxy metrics (stand-ins for data not freely available): "
                + "; ".join(proxies)
                + ".",
            )
        )
    unadjusted = [k.label for k in kpis if k.padj_status == "unadjusted"]
    if unadjusted:
        out.append(
            Caveat(
                kind="unadjusted_defence",
                text="Not possession-adjusted (possession data missing): "
                + "; ".join(unadjusted)
                + ".",
            )
        )
    value: MarketValueFact | None = sheet["market_value"]
    if value is None:
        out.append(
            Caveat(
                kind="no_market_value",
                text="Transfermarkt estimated market value: Not available.",
            )
        )
    elif value.is_stale:
        out.append(
            Caveat(
                kind="stale_value",
                text="The Transfermarkt estimated market value comes from a stale snapshot "
                f"(Transfermarkt as of {value.tm_last_updated.isoformat()}).",
            )
        )
    if sheet["implied_value"] is not None:
        out.append(Caveat(kind="value_model", text=VALUE_CAVEAT))
    if not sheet["comparables"]:
        out.append(
            Caveat(
                kind="no_comparables",
                text="Comparable players: Not available (the player is not ranked on "
                "every KPI of the position group).",
            )
        )
    fit: FitFact | None = sheet["fit"]
    if fit is not None and fit.same_club:
        out.append(
            Caveat(
                kind="same_club",
                text=f"The player already plays for {fit.team_name}; the fit section "
                "compares them with the club's need, not as a signing.",
            )
        )
    return out


def receipts(sheet: dict[str, Any], kpis: list[KpiFact]) -> list[Receipt]:
    """Every source behind the sheet with the newest as-of used from it."""
    newest: dict[str, str | None] = {}

    def add(source: str, as_of: str | None) -> None:
        old = newest.get(source)
        newest[source] = max(filter(None, (old, as_of)), default=None)

    for k in kpis:
        add(k.source, k.as_of)
    if sheet["status_as_of"] is not None:
        add("fpl", sheet["status_as_of"])
    value: MarketValueFact | None = sheet["market_value"]
    if value is not None:
        add(value.source, value.tm_last_updated.isoformat())
    if sheet["role"] is not None:
        add("scout train (role archetypes)", sheet["role"].trained_at)
    if sheet["implied_value"] is not None:
        add("scout train (value model)", sheet["implied_value"].trained_at)
    return [Receipt(source=s, as_of=a) for s, a in sorted(newest.items())]


def _role(engine: Engine, player_id: int, season_mode: str) -> RoleFact | None:
    with make_session_factory(engine)() as session:
        row = session.scalars(
            select(PlayerRole).where(
                PlayerRole.player_id == player_id, PlayerRole.season_mode == season_mode
            )
        ).first()
    if row is None:
        return None
    return RoleFact(label=row.label, trained_at=row.trained_at.isoformat(), git_sha=row.git_sha)


def _implied_value(engine: Engine, player_id: int, season_id: str) -> ImpliedValueFact | None:
    with make_session_factory(engine)() as session:
        row = session.scalars(
            select(PlayerValueScore).where(
                PlayerValueScore.player_id == player_id, PlayerValueScore.season_id == season_id
            )
        ).first()
    if row is None:
        return None
    return ImpliedValueFact(
        implied_value_eur=row.implied_value_eur,
        band_low_eur=row.band_low_eur,
        band_high_eur=row.band_high_eur,
        label=row.value_label,
        trained_at=row.trained_at.isoformat(),
        git_sha=row.git_sha,
        caveat=VALUE_CAVEAT,
    )


def _comparables(
    engine: Engine,
    player_id: int,
    config: AppConfig,
    season_mode: str,
    names: Mapping[int, tuple[str, int]],
    team_names: Mapping[int, str],
) -> list[ComparableFact]:
    try:
        hits = find_similar(
            engine, player_id, config, k=config.settings.reports.comparables_k,
            season_mode=season_mode,
        )  # fmt: skip
    except NotFoundError:
        return []
    out: list[ComparableFact] = []
    for hit in hits:
        name, team = names.get(hit.player_id, (str(hit.player_id), -1))
        out.append(
            ComparableFact(
                player_id=hit.player_id,
                player_name=name,
                team_name=team_names.get(team),
                similarity=hit.similarity,
            )
        )
    return out


def build_fact_sheet(
    engine: Engine,
    player_id: int,
    config: AppConfig,
    *,
    team_id: int | None = None,
    season_mode: str = "blended",
    benchmark: Benchmark | None = None,
    as_of: date | None = None,
) -> FactSheet:
    """Assemble the fact sheet for ``player_id`` from the warehouse.

    Args:
        engine: Warehouse engine.
        player_id: Player to describe.
        config: Validated config.
        team_id: Club whose need the report addresses (adds the fit section).
        season_mode: ``blended`` (default) or ``current``.
        benchmark: Benchmark for the club's diagnosis (config default when ``None``).
        as_of: Date ages are measured from (today by default).

    Raises:
        NotFoundError: If the player has no current-season profile or the club is unknown.
    """
    today = as_of or date.today()
    profiles = player_profiles(engine)
    match = profiles[profiles["player_id"] == player_id]
    if match.empty:
        raise NotFoundError(
            f"player {player_id} has no current-season minutes", details={"player_id": player_id}
        )
    profile = match.to_dict(orient="records")[0]
    group = _text(profile["position_group"])
    if group is None:
        raise NotFoundError(
            f"player {player_id} has no position group", details={"player_id": player_id}
        )
    if team_id is not None:
        with make_session_factory(engine)() as session:
            if session.get(DimTeam, team_id) is None:
                raise NotFoundError(f"no club with id {team_id}", details={"team_id": team_id})
    ctx = season_context(engine)
    features = player_features(engine, season_mode)
    rows = features[features["player_id"] == player_id].to_dict(orient="records")
    kpis = kpi_facts(rows, group, config)
    effective = max((_opt(r["effective_minutes"]) or 0.0 for r in rows), default=None)
    used_previous = any(bool(r.get("used_previous_season")) for r in rows)
    strengths, concerns = strengths_and_concerns(kpis, config.settings.reports.max_listed)

    values = latest_market_values(engine)
    mine = values[values["player_id"] == player_id].to_dict(orient="records")
    mv = preferred_market_value(mine, config.settings.recommend.market_value_precedence)
    market_value = (
        MarketValueFact(
            value_eur=mv.value_eur,
            tm_last_updated=mv.tm_last_updated,
            source=mv.source,
            is_stale=mv.is_stale,
        )
        if mv is not None
        else None
    )
    names = {
        int(p): (str(n), int(t))
        for p, n, t in zip(
            profiles["player_id"], profiles["canonical_name"], profiles["current_team_id"],
            strict=True,
        )
    }  # fmt: skip
    fit: FitFact | None = None
    if team_id is not None:
        assessment = assess_player(
            engine, team_id, player_id, config,
            benchmark=benchmark, season_mode=season_mode, as_of=today,
        )  # fmt: skip
        fit = fit_fact(assessment, config)
    club = int(profile["current_team_id"])
    sheet: dict[str, Any] = {
        "player_id": player_id,
        "player_name": str(profile["canonical_name"]),
        "team_id": club,
        "team_name": ctx.team_names.get(club, str(club)),
        "position_group": group,
        "birth_date": _date(profile["birth_date"]),
        "age": age_on(profile["birth_date"], today),
        "as_of": today,
        "season_mode": season_mode,
        "current_season": ctx.current,
        "previous_season": ctx.previous if season_mode == "blended" and used_previous else None,
        "minutes": float(profile["season_minutes"] or 0.0),
        "effective_minutes": effective,
        "fpl_status": _text(profile["fpl_status"]),
        "chance_of_playing": _opt(profile["chance_of_playing"]),
        "status_as_of": _text(profile["status_as_of"]),
        "contract_expiry": _date(profile["contract_expiry"]),
        "market_value": market_value,
        "kpis": kpis,
        "strengths": strengths,
        "concerns": concerns,
        "role": _role(engine, player_id, season_mode),
        "comparables": _comparables(engine, player_id, config, season_mode, names, ctx.team_names),
        "implied_value": _implied_value(engine, player_id, ctx.current),
        "fit": fit,
    }
    sheet["caveats"] = caveats(sheet, kpis, config)
    sheet["sources"] = receipts(sheet, kpis)
    return FactSheet.model_validate(sheet)


def _walk(value: object, key: str, out: set[float]) -> None:
    """Collect numbers from a dumped fact sheet, with the scales reports display them in."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number):
            return
        out.add(number)
        if key.endswith("_eur"):
            out.add(number / EUR_PER_MILLION)  # "€45.0m"
        if key in {"weight", "similarity"} or key.startswith("weights_used"):
            out.add(number * PERCENT)  # "40%", "similarity 87%"
        return
    if isinstance(value, str):
        out.update(float(n) for n in _NUMBER.findall(value))
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            _walk(v, f"{key}.{k}" if key.startswith("weights_used") else str(k), out)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, key, out)


def allowed_numbers(sheet: FactSheet) -> set[float]:
    """Every number a report about ``sheet`` may contain (before rounding)."""
    out: set[float] = set()
    _walk(sheet.model_dump(mode="json"), "", out)
    return out


def allowed_text(sheet: FactSheet) -> str:
    """All text in the sheet (names, labels, caveats), for the proper-noun check."""
    parts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            for k, v in value.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(sheet.model_dump(mode="json"))
    return "\n".join(parts)
