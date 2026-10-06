"""Freshness and methodology: "can I trust these numbers?" (US-08, PRD §13 /methodology)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from scout.api.deps import ApiState, State
from scout.api.errors import ERROR_RESPONSES
from scout.api.schemas import (
    ArrivalOut,
    BacktestResponse,
    ClubBacktestOut,
    FreshnessResponse,
    KpiDefinitionOut,
    MethodologyResponse,
    ModelRunOut,
    PredictedNeedOut,
    SourceFreshnessOut,
    TeamKpiDefinitionOut,
)
from scout.db.doctor import run_doctor
from scout.db.models import PlayerRole, PlayerValueScore
from scout.db.session import make_session_factory
from scout.engines.backtest import run_backtest
from scout.errors import ConfigError, InvalidRequestError
from scout.ml.value_model import CAVEAT

router = APIRouter(prefix="/meta", tags=["meta"], responses=ERROR_RESPONSES)

# Known limitations shown on the methodology page (PRD §7.2, §17, CLAUDE.md gotchas).
LIMITATIONS = [
    "Player-level pressing is a proxy: possession-adjusted defensive activity (tackles + "
    "recoveries, plus clearances/blocks/interceptions for defenders). Pressure counts are not "
    "freely available for the current Premier League.",
    "Ball progression is a proxy (xGBuildup and xGChain per 90). True progressive passes and "
    "carries need event data, which is not part of the MVP.",
    "Understat xA (xG of shots from a player's key passes) and FPL/Opta xA are defined "
    "differently; each KPI uses one source and says which.",
    "Defensive volume KPIs are possession-adjusted only where FotMob possession exists; "
    "otherwise they are flagged 'unadjusted'.",
    "Early in the season rates lean on last season (blending) and are shrunk toward the "
    "position-group average; minutes and peer counts are always shown.",
    "Transfermarkt estimated market values are estimates, not fees. The "
    "transfermarkt-datasets fallback stopped updating in mid-2026 and is labelled stale.",
    "The stats-implied value model learns the market's own biases and is trained on past "
    "Premier League seasons of current players only (survivorship bias). It is not a fee "
    "prediction.",
    "Candidates are Premier League players only. Goalkeeper ratings are limited: free data has "
    "no post-shot xG, distribution, claiming or sweeping numbers, so shot-stopping is a proxy.",
    "FPL data fields are undocumented and can change; `scout doctor` validates the schema on "
    "every run.",
]


@router.get("/freshness", response_model=FreshnessResponse)
def freshness(state: State) -> FreshnessResponse:
    """Per-source last fetch, mapping coverage, staleness flags and validation status."""

    def compute() -> FreshnessResponse:
        report = run_doctor(state.settings, state.config)
        build = report.last_build or {}
        summary = build.get("validation_summary")
        return FreshnessResponse(
            warehouse_version=state.warehouse_version(),
            validation_summary=str(summary) if summary is not None else None,
            sources=[
                SourceFreshnessOut(
                    source=f.source,
                    last_fetched=f.last_fetched,
                    age_hours=f.age_hours,
                    stale=f.stale,
                )
                for f in report.freshness
            ],
            coverage=report.coverage,
            review_count=report.review_count,
            fpl_schema=report.fpl_schema,
            warnings=report.warnings,
        )

    return state.cached(("freshness",), compute)


def _model_runs(state: ApiState) -> list[ModelRunOut]:
    runs: list[ModelRunOut] = []
    with make_session_factory(state.engine)() as session:
        for name, model in (("role archetypes", PlayerRole), ("value model", PlayerValueScore)):
            trained_at, git_sha, rows = session.execute(
                select(func.max(model.trained_at), func.max(model.git_sha), func.count(model.id))
            ).one()
            runs.append(ModelRunOut(name=name, trained_at=trained_at, git_sha=git_sha, rows=rows))
    return runs


@router.get("/methodology", response_model=MethodologyResponse)
def methodology(state: State) -> MethodologyResponse:
    """KPI definitions, weights, proxies, thresholds, model runs and known limitations."""
    state.season()  # a built warehouse is needed for the model runs
    cfg = state.config
    method = cfg.settings.methodology
    diag = cfg.settings.diagnosis
    parameters: dict[str, float | int | str] = {
        "blend_lambda": method.blend_lambda,
        "prev_season_minutes_cap": method.prev_season_minutes_cap,
        "default_shrinkage_k": method.default_shrinkage_k,
        "percentile_min_minutes": method.percentile_min_minutes,
        "possession_multiplier_min": method.possession_multiplier_min,
        "possession_multiplier_max": method.possession_multiplier_max,
        "roles_min_minutes": method.roles_min_minutes,
        "default_benchmark": diag.default_benchmark,
        "weak_link_min_minutes_share": diag.weak_link_min_minutes_share,
        "weak_link_max_percentile": diag.weak_link_max_percentile,
        "weak_link_min_kpi_weight": diag.weak_link_min_kpi_weight,
        "depth_single_player_share": diag.depth_single_player_share,
        "depth_backup_min_percentile": diag.depth_backup_min_percentile,
        "age_risk_min_weighted_age": diag.age_risk_min_weighted_age,
        "contract_risk_months": diag.contract_risk_months,
    }
    bands = cfg.settings.reports.bands
    return MethodologyResponse(
        kpis=[
            KpiDefinitionOut(
                kpi=kpi,
                label=d.label,
                source=d.source,
                higher_is_better=d.higher_is_better,
                is_proxy=d.is_proxy,
                proxy_for=d.proxy_for,
                possession_adjusted=d.possession_adjusted,
            )
            for kpi, d in cfg.kpis.kpis.items()
        ],
        position_groups={g: dict(c.weights) for g, c in cfg.kpis.position_groups.items()},
        group_caveats={g: c.caveat for g, c in cfg.kpis.position_groups.items() if c.caveat},
        team_kpis=[
            TeamKpiDefinitionOut(
                kpi=kpi,
                label=d.label,
                source=d.source,
                higher_is_better=d.higher_is_better,
                responsible_groups=list(d.responsible_groups),
            )
            for kpi, d in cfg.kpis.team_kpis.items()
        ],
        fit_weights={str(k): v for k, v in cfg.fit_weights.components.items()},
        upgrade_gate_min_delta=cfg.fit_weights.upgrade_gate_min_delta,
        peak_age={str(g): w for g, w in cfg.fit_weights.peak_age.items()},
        parameters=parameters,
        percentile_bands=bands.model_dump(),
        value_model_caveat=CAVEAT,
        models=state.cached(("model_runs",), lambda: _model_runs(state)),
        limitations=LIMITATIONS,
    )


BACKTEST_CAVEAT = (
    "Exploratory: clubs sign players for many reasons (injuries, sales, loans, opportunity), "
    "so a need that was not filled is not proof the diagnosis was wrong."
)


@router.get("/backtest", response_model=BacktestResponse)
def backtest(state: State) -> BacktestResponse:
    """Did last season's top needs match the position groups clubs then signed? (US-16)."""
    state.season()

    def compute() -> BacktestResponse:
        try:
            r = run_backtest(state.engine, state.config)
        except ConfigError as exc:
            raise InvalidRequestError(exc.message) from exc
        return BacktestResponse(
            as_of_season=r.as_of_season,
            signing_season=r.signing_season,
            benchmark=r.benchmark,
            top_n=r.top_n,
            precision=r.precision,
            baseline_precision=r.baseline_precision,
            random_precision=r.random_precision,
            hit_rate=r.hit_rate,
            evaluated=r.evaluated,
            skipped=r.skipped,
            clubs=[
                ClubBacktestOut(
                    team_id=c.team_id,
                    team_name=c.team_name,
                    predicted=[
                        PredictedNeedOut(position_group=p.position_group, severity=p.severity)
                        for p in c.predicted
                    ],
                    arrivals=[
                        ArrivalOut(
                            player_id=a.player_id,
                            player_name=a.player_name,
                            position_group=a.position_group,
                            minutes=a.minutes,
                        )
                        for a in c.arrivals
                    ],
                    hits=c.hits,
                    precision=c.precision,
                    baseline_groups=c.baseline_groups,
                    baseline_precision=c.baseline_precision,
                    random_precision=c.random_precision,
                )
                for c in r.clubs
            ],
            history_as_of=r.history_as_of,
            arrivals_as_of=r.arrivals_as_of,
            caveat=BACKTEST_CAVEAT,
        )

    return state.cached(("backtest",), compute)
