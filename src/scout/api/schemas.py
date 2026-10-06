"""Pydantic response models shared by every router (PRD §12).

Every number a response carries either has its receipt next to it (``source`` and
``as_of``, or Transfermarkt's own as-of date for market values) or belongs to an object
that does. Missing values are ``null`` and the web app renders them as "Not available".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scout.reports.facts import FactSheet, ImpliedValueFact, KpiFact

SeasonMode = Literal["blended", "current"]
BenchmarkName = Literal["top6", "top4", "league", "custom"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class ErrorBody(_Out):
    """Machine-readable error details."""

    code: str = Field(description="Stable error code, e.g. 'not_found'.")
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(_Out):
    """The single error schema returned by every endpoint."""

    error: ErrorBody


class HealthResponse(_Out):
    """Liveness plus warehouse version."""

    status: Literal["ok"]
    version: str = Field(description="Engine version.")
    warehouse_version: str | None = Field(
        description="When the warehouse was last built; null until `scout build` has run."
    )


# --- meta ---------------------------------------------------------------------------


class SourceFreshnessOut(_Out):
    """Newest snapshot of one source."""

    source: str
    last_fetched: datetime
    age_hours: float
    stale: bool


class FreshnessResponse(_Out):
    """Per-source freshness, mapping coverage and validation status (US-08)."""

    warehouse_version: str | None
    validation_summary: str | None
    sources: list[SourceFreshnessOut]
    coverage: dict[str, float] = Field(description="Share of FPL minutes mapped per source.")
    review_count: int = Field(description="Records entity resolution could not map.")
    fpl_schema: str
    warnings: list[str]


class KpiDefinitionOut(_Out):
    """One player KPI definition from ``config/kpis.yaml``."""

    kpi: str
    label: str
    source: str
    higher_is_better: bool
    is_proxy: bool
    proxy_for: str | None
    possession_adjusted: bool


class TeamKpiDefinitionOut(_Out):
    """One team KPI and the position groups a shortfall maps to."""

    kpi: str
    label: str
    source: str
    higher_is_better: bool
    responsible_groups: list[str]


class ModelRunOut(_Out):
    """When an ML output stored in the warehouse was produced."""

    name: str
    trained_at: datetime | None
    git_sha: str | None
    rows: int


class MethodologyResponse(_Out):
    """Definitions, weights, thresholds and limitations (US-08, PRD §8)."""

    kpis: list[KpiDefinitionOut]
    position_groups: dict[str, dict[str, float]] = Field(description="Group -> KPI -> weight.")
    team_kpis: list[TeamKpiDefinitionOut]
    fit_weights: dict[str, float]
    upgrade_gate_min_delta: float
    peak_age: dict[str, tuple[int, int]]
    parameters: dict[str, float | int | str] = Field(
        description="Methodology and diagnosis thresholds from config/settings.yaml."
    )
    percentile_bands: dict[str, float]
    value_model_caveat: str
    models: list[ModelRunOut]
    limitations: list[str]


# --- teams ----------------------------------------------------------------------------


class TeamOut(_Out):
    """A club in the current season."""

    team_id: int
    name: str
    short_name: str | None
    aliases: list[str]


class TeamSearchHit(_Out):
    """A club search result and how it matched (US-01)."""

    team_id: int
    name: str
    matched: str = Field(description="The name or alias that matched.")
    kind: Literal["exact", "prefix", "fuzzy"]
    score: float


class TeamRef(_Out):
    """A club id with its name."""

    team_id: int
    name: str


class KpiGapOut(_Out):
    """Club vs benchmark on one KPI of a position group (percentile points)."""

    kpi: str
    label: str
    weight: float
    is_proxy: bool
    club_score: float | None
    benchmark_score: float | None
    gap: float | None = Field(description="Benchmark minus club; positive = club trails.")


class EvidenceOut(_Out):
    """One number behind a need, with its receipt."""

    player_id: int
    player_name: str
    kpi: str
    label: str
    raw_p90: float | None = Field(description="This season's per-90 value.")
    value: float | None = Field(
        description="Per-90 value in the requested season mode (what the percentile ranks)."
    )
    percentile: float | None
    n_peers: int
    minutes: float
    source: str
    as_of: str | None
    is_proxy: bool
    padj_status: str | None


class WeakLinkOut(_Out):
    """A regular starter rating poorly on an important KPI (US-03)."""

    player_id: int
    player_name: str
    kpi: str
    label: str
    percentile: float
    minutes_share: float


class RiskOut(_Out):
    """Depth, age or contract risk in a position group."""

    kind: str
    detail: str
    player_id: int | None
    player_name: str | None
    value: float | None


class TeamNeedOut(_Out):
    """A team-level KPI shortfall mapped to the groups responsible (PRD §8.8 step 7)."""

    kpi: str
    label: str
    higher_is_better: bool
    club_value: float
    club_percentile: float
    benchmark_value: float
    benchmark_percentile: float
    gap: float
    n_peers: int
    matches: int
    previous_matches: int
    responsible_groups: list[str]
    source: str
    as_of: str | None


class NeedOut(_Out):
    """A ranked position-group need (US-02)."""

    rank: int
    need_id: str
    position_group: str
    severity: float
    gaps: list[KpiGapOut]
    evidence: list[EvidenceOut]
    weak_links: list[WeakLinkOut]
    risks: list[RiskOut]
    team_needs: list[str] = Field(description="KPI ids of team needs this group shares.")


class DiagnosisResponse(_Out):
    """A club's needs against a benchmark, every group ranked (PRD §8.8)."""

    team_id: int
    team_name: str
    season_mode: SeasonMode
    current_season: str
    benchmark: BenchmarkName
    benchmark_teams: list[TeamRef]
    needs: list[NeedOut]
    team_needs: list[TeamNeedOut]


class MarketValueOut(_Out):
    """Transfermarkt estimated market value with Transfermarkt's own as-of date."""

    value_eur: int
    tm_last_updated: date
    source: str
    is_stale: bool


class FitOut(_Out):
    """FitScore (0-100) with its components and the weights actually used."""

    total: float | None
    components: dict[str, float | None]
    weights_used: dict[str, float]


class CandidateOut(_Out):
    """One shortlisted player (US-04)."""

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
    market_value: MarketValueOut | None
    implied_value: ImpliedValueFact | None = Field(
        description="Stats-implied value band (Moneyball view, US-11); null if not scored."
    )
    fit: FitOut
    gate: Literal["upgrade", "sideways", "no_incumbent", "insufficient_data"]
    evidence: list[EvidenceOut]


class IncumbentOut(_Out):
    """The club's minutes leader in the group: the bar for the upgrade gate."""

    player_id: int
    player_name: str
    minutes: float
    need_fill: float | None


class DeficitOut(_Out):
    """A KPI the club trails on, weighted for NeedFill (KPI weight x gap)."""

    kpi: str
    label: str
    weight: float


class ShortlistResponse(_Out):
    """Ranked candidates for one need, and how many each filter removed (US-04/05)."""

    team_id: int
    team_name: str
    need_id: str
    position_group: str
    season_mode: SeasonMode
    deficits: list[DeficitOut]
    incumbent: IncumbentOut | None
    candidates: list[CandidateOut]
    excluded: dict[str, int]


# --- players --------------------------------------------------------------------------


class PlayerSearchHit(_Out):
    """A player search result."""

    player_id: int
    name: str
    team_id: int
    team_name: str
    position_group: str | None
    matched: str
    kind: Literal["exact", "prefix", "fuzzy"]
    score: float


class SimilarPlayerOut(_Out):
    """A similar player in the same position group."""

    player_id: int
    player_name: str
    team_id: int | None
    team_name: str | None
    similarity: float = Field(description="Cosine similarity, -1 to 1.")


class SimilarResponse(_Out):
    """Top-k similar players (US-09)."""

    player_id: int
    player_name: str
    position_group: str
    season_mode: SeasonMode
    results: list[SimilarPlayerOut]


class ReportOut(_Out):
    """Scouting report text and how it was produced."""

    text: str
    engine: Literal["template", "ollama"]
    requested_engine: Literal["template", "ollama"]
    fallback_reason: str | None
    violations: list[str]


class ReportResponse(_Out):
    """A grounded scouting report with the fact sheet behind it (US-06)."""

    report: ReportOut
    facts: FactSheet


class CompareRow(_Out):
    """One KPI for both players."""

    kpi: str
    label: str
    is_proxy: bool
    is_need: bool = Field(description="A KPI the club trails on (when team_id is given).")
    a: KpiFact | None
    b: KpiFact | None
    delta: float | None = Field(description="Percentile of a minus percentile of b.")


class ComparePlayer(_Out):
    """Header facts of one compared player."""

    player_id: int
    player_name: str
    team_id: int
    team_name: str
    position_group: str
    age: float | None
    minutes: float
    effective_minutes: float | None
    market_value: MarketValueOut | None


class CompareResponse(_Out):
    """Side-by-side percentiles for two players (US-07)."""

    season_mode: SeasonMode
    a: ComparePlayer
    b: ComparePlayer
    team: TeamRef | None
    rows: list[CompareRow]


# --- backtest -------------------------------------------------------------------------


class ArrivalOut(_Out):
    """A player who joined a club for this season and has played for it."""

    player_id: int
    player_name: str
    position_group: str | None
    minutes: float


class PredictedNeedOut(_Out):
    """One of a club's top needs at the end of the backtest season."""

    position_group: str
    severity: float


class ClubBacktestOut(_Out):
    """Predicted needs vs actual arrivals for one club."""

    team_id: int
    team_name: str
    predicted: list[PredictedNeedOut]
    arrivals: list[ArrivalOut]
    hits: list[str]
    precision: float | None
    baseline_groups: list[str]
    baseline_precision: float | None
    random_precision: float | None


class BacktestResponse(_Out):
    """Last season's diagnosis vs this season's arrivals (US-16, exploratory)."""

    as_of_season: str = Field(description="Season the needs were diagnosed at the end of.")
    signing_season: str = Field(description="Season whose arrivals are the outcome.")
    benchmark: str
    top_n: int
    precision: float | None = Field(description="Mean precision@n over evaluated clubs.")
    baseline_precision: float | None = Field(
        description="Same for the n most-signed groups at the other clubs."
    )
    random_precision: float | None = Field(description="Expected precision of random groups.")
    hit_rate: float | None = Field(description="Share of clubs with at least one hit.")
    evaluated: int
    skipped: dict[str, int]
    clubs: list[ClubBacktestOut]
    history_as_of: str | None
    arrivals_as_of: str | None
    caveat: str
