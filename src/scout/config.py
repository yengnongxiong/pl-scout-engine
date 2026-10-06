"""Configuration: environment settings plus validated YAML files in ``config/``.

Thresholds, weights, rate limits and mappings live in YAML rather than code (CLAUDE.md
"Config over code"). Each file is parsed into a pydantic model so a typo or a weight set
that does not sum to 1.0 fails fast with a :class:`~scout.errors.ConfigError`.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from scout.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PositionGroup = Literal["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
Source = Literal[
    "fpl", "understat", "fotmob", "transfermarkt", "transfermarkt_datasets", "vaastav", "statsbomb"
]

# Numeric fact_team_match columns a team KPI can be built from (PRD §11).
TeamMatchColumn = Literal[
    "xg", "xga", "npxg", "npxga", "ppda", "ppda_allowed", "deep", "deep_allowed",
    "set_piece_xg", "set_piece_xga", "open_play_xga", "possession",
]  # fmt: skip

WEIGHT_SUM_TOLERANCE = 1e-6
OUTFIELD_GROUPS: list[PositionGroup] = ["CB", "FB", "DM", "CM", "AM", "W", "ST"]


class Settings(BaseSettings):
    """Environment-driven settings (prefix ``SCOUT_``, except ``REPORT_ENGINE``)."""

    model_config = SettingsConfigDict(env_prefix="SCOUT_", env_file=".env", extra="ignore")

    config_dir: Path = PROJECT_ROOT / "config"
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'warehouse' / 'scout.db'}"
    report_engine: Literal["template", "ollama"] = Field(
        default="template", validation_alias="REPORT_ENGINE"
    )
    ollama_model: str | None = None
    log_level: str = "INFO"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MethodologyConfig(_Strict):
    """PRD §8.2-8.6 and §8.10 methodology parameters."""

    blend_lambda: float = Field(ge=0.0, le=1.0)
    prev_season_minutes_cap: int = Field(gt=0)
    default_shrinkage_k: float = Field(gt=0.0)
    possession_multiplier_min: float = Field(gt=0.0)
    possession_multiplier_max: float = Field(gt=0.0)
    percentile_min_minutes: int = Field(ge=0)
    roles_min_minutes: int = Field(ge=0)

    @model_validator(mode="after")
    def _clip_range_ordered(self) -> MethodologyConfig:
        if self.possession_multiplier_min > self.possession_multiplier_max:
            raise ValueError("possession_multiplier_min must be <= possession_multiplier_max")
        return self


class DiagnosisConfig(_Strict):
    """PRD §8.8 diagnosis thresholds."""

    default_benchmark: Literal["top6", "top4", "league", "custom"]
    benchmark_sizes: dict[Literal["top6", "top4"], int]
    weak_link_min_minutes_share: float = Field(ge=0.0, le=1.0)
    weak_link_max_percentile: float = Field(ge=0.0, le=100.0)
    weak_link_min_kpi_weight: float = Field(ge=0.0, le=1.0)
    depth_single_player_share: float = Field(ge=0.0, le=1.0)
    depth_backup_min_percentile: float = Field(ge=0.0, le=100.0)
    age_risk_min_weighted_age: float = Field(gt=0.0)
    contract_risk_months: int = Field(gt=0)


class RecommendConfig(_Strict):
    """PRD §8.9 shortlist defaults and hard filters."""

    default_limit: int = Field(gt=0)
    # FPL status codes never shortlisted (e.g. u = left the club).
    excluded_statuses: list[str] = Field(default_factory=list)
    # Transfermarkt estimated market value sources, most preferred first.
    market_value_precedence: list[
        Literal["override", "transfermarkt", "transfermarkt_datasets"]
    ] = Field(min_length=1)
    # Show candidates that fail the upgrade gate only when asked (PRD §8.9).
    hide_sideways_by_default: bool = True


class IngestConfig(_Strict):
    """Scraping etiquette: User-Agent, cache TTL, retries and per-source rate limits."""

    base_urls: dict[Source, str] = Field(default_factory=dict)
    history_seasons_back: int = Field(default=3, ge=1)
    possession_sum_tolerance: float = Field(default=0.02, ge=0.0, le=1.0)
    tm_datasets_competition_id: str = "GB1"
    statsbomb_competition_id: int = 2
    statsbomb_season_id: int = 27
    statsbomb_max_matches: int = Field(default=10, ge=1)
    user_agent: str = Field(min_length=1)
    cache_ttl_hours: float = Field(gt=0.0)
    max_retries: int = Field(ge=0)
    backoff_initial_seconds: float = Field(ge=0.0)
    backoff_max_seconds: float = Field(ge=0.0)
    timeout_seconds: float = Field(gt=0.0)
    min_body_bytes: int = Field(ge=0)
    interstitial_markers: list[str]
    rate_limits: dict[Source, float]

    @model_validator(mode="after")
    def _positive_rates(self) -> IngestConfig:
        bad = [s for s, r in self.rate_limits.items() if r <= 0]
        if bad:
            raise ValueError(f"rate limits must be positive: {bad}")
        return self


class EntityResolutionConfig(_Strict):
    """Thresholds for cross-source player matching (CLAUDE.md "Known gotchas")."""

    accept_score: float = Field(ge=0.0, le=100.0)
    min_margin: float = Field(ge=0.0, le=100.0)
    target_minutes_coverage: float = Field(ge=0.0, le=1.0)


class DoctorConfig(_Strict):
    """Freshness thresholds for ``scout doctor`` (PRD §14 observability)."""

    default_stale_after_hours: float = Field(gt=0.0)
    stale_after_hours: dict[Source, float] = Field(default_factory=dict)

    def threshold(self, source: str) -> float:
        """Staleness threshold in hours for ``source``."""
        return next(
            (h for s, h in self.stale_after_hours.items() if s == source),
            self.default_stale_after_hours,
        )


class ValidationConfig(_Strict):
    """Thresholds for staged-table validation (CLAUDE.md rule 12)."""

    max_match_minutes: int = Field(gt=0)


class MLConfig(_Strict):
    """PRD §8.10 ML parameters."""

    seed: int
    gmm_k_min: int = Field(gt=0)
    gmm_k_max: int = Field(gt=0)
    # Similar-player search: brute force (default; fastest at ~600 players, see
    # scripts/bench_knn.py) or the hand-written k-d tree.
    similarity_method: Literal["brute", "kdtree"] = "brute"
    # Neighbours listed per sanity example in docs/EVALUATION.md (PRD §8.11).
    similarity_examples_k: int = Field(default=3, gt=0)
    # Role archetypes: automatic label ("high X, low Y") -> scout-friendly name.
    role_renames: dict[str, str] = Field(default_factory=dict)
    # Position groups clustered into role archetypes (goalkeepers are a role of their own).
    role_groups: list[PositionGroup] = Field(default_factory=lambda: list(OUTFIELD_GROUPS))


class ValueModelConfig(_Strict):
    """PRD §8.10 step 3: stats-implied market value model."""

    # Training label: the Transfermarkt estimated market value nearest each season's last
    # kickoff, within this many days before / after it.
    label_window_days_before: int = Field(ge=0)
    label_window_days_after: int = Field(ge=0)
    # Player-seasons below this many minutes are too noisy to learn a value from.
    min_minutes: float = Field(ge=0.0)
    # Counting stats turned into per-90 features (player_season.sql columns).
    per90_stats: list[str] = Field(min_length=1)
    # Baseline: median log value per position group x age bucket (upper bounds, years).
    age_bucket_edges: list[float] = Field(min_length=1)
    # Lower / upper quantile models for the uncertainty band.
    quantiles: tuple[float, float]
    max_iter: int = Field(gt=0)
    learning_rate: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _valid(self) -> ValueModelConfig:
        low, high = self.quantiles
        if not 0.0 < low < 0.5 < high < 1.0:
            raise ValueError(f"quantiles must straddle the median: {self.quantiles}")
        if self.age_bucket_edges != sorted(self.age_bucket_edges):
            raise ValueError("age_bucket_edges must be ascending")
        return self


class ReportBands(_Strict):
    """PRD §9 percentile band lower bounds."""

    elite: float
    strong: float
    above_average: float
    below_average: float

    @model_validator(mode="after")
    def _descending(self) -> ReportBands:
        if not self.elite > self.strong > self.above_average > self.below_average:
            raise ValueError("report bands must be strictly descending")
        return self


class OllamaConfig(_Strict):
    """Optional local LLM rewrite (PRD §9 step 3). The model name comes from the environment."""

    base_url: str = "http://localhost:11434/"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=120.0, gt=0.0)


class ReportsConfig(_Strict):
    """Report generation settings (PRD §9)."""

    bands: ReportBands
    # Strengths / concerns listed per report.
    max_listed: int = Field(default=3, gt=0)
    # Comparable players named in a report.
    comparables_k: int = Field(default=3, gt=0)
    # Fewer effective (blended) minutes than this adds a small-sample caveat.
    small_sample_minutes: float = Field(default=900.0, ge=0.0)
    # FitScore at or above this reads as a strong fit in the verdict.
    strong_fit_score: float = Field(default=70.0, ge=0.0, le=100.0)
    # Relative tolerance when matching numbers in generated text to the fact sheet,
    # on top of the rounding the text itself shows.
    grounding_tolerance: float = Field(default=1e-6, ge=0.0)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)


class ApiConfig(_Strict):
    """Read-only API settings (PRD §12)."""

    # Entries kept in the in-process LRU cache for hot endpoints (dsa.lru_cache).
    cache_capacity: int = Field(default=256, gt=0)
    # Search: results per query and the fuzzy-suggestion cut-off (rapidfuzz WRatio, 0-100).
    search_limit: int = Field(default=8, gt=0)
    search_max_limit: int = Field(default=25, gt=0)
    fuzzy_cutoff: float = Field(default=75.0, ge=0.0, le=100.0)
    # Similar players per request (default and upper bound).
    similar_k: int = Field(default=10, gt=0)
    similar_max_k: int = Field(default=50, gt=0)
    # Upper bound on shortlist length per request.
    max_shortlist: int = Field(default=50, gt=0)


class AgeCurvesConfig(_Strict):
    """PRD §8.10 step 4 / US-18: delta-method aging curves from past FPL seasons."""

    # player_season.sql counting stats turned into per-90 rates -> display label. Only stats
    # every past season has (FPL defensive stats start in 2025-26).
    metrics: dict[str, str] = Field(
        default_factory=lambda: {
            "xg": "xG (FPL, per 90)",
            "xa": "xA (FPL, per 90)",
            "goals": "Goals (per 90)",
            "assists": "Assists (per 90)",
        },
        min_length=1,
    )
    # Both seasons of a pair need this many minutes.
    min_minutes: float = Field(default=900.0, ge=0.0)
    # An age with fewer pairs shows "Not available" instead of a noisy average.
    min_pairs: int = Field(default=15, gt=0)
    age_min: int = Field(default=18, gt=0)
    age_max: int = Field(default=36, gt=0)


class BacktestConfig(_Strict):
    """PRD §8.11 / US-16: did last season's diagnosis point at the positions clubs signed?"""

    # Needs compared per club (precision@n).
    top_n: int = Field(default=3, gt=0)
    # A summer arrival counts once they have played this many minutes for the new club.
    arrival_min_minutes: float = Field(default=1.0, ge=0.0)


class EngineSettings(_Strict):
    """Contents of ``config/settings.yaml``."""

    methodology: MethodologyConfig
    diagnosis: DiagnosisConfig
    recommend: RecommendConfig
    ingest: IngestConfig
    entity_resolution: EntityResolutionConfig
    doctor: DoctorConfig
    validation: ValidationConfig
    ml: MLConfig
    value_model: ValueModelConfig
    reports: ReportsConfig
    api: ApiConfig = Field(default_factory=ApiConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    age_curves: AgeCurvesConfig = Field(default_factory=AgeCurvesConfig)


class KpiDef(_Strict):
    """One player KPI definition (PRD §8.7)."""

    label: str
    source: Source
    higher_is_better: bool
    is_proxy: bool
    proxy_for: str | None = None
    possession_adjusted: bool = False
    shrinkage_k: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _proxy_explained(self) -> KpiDef:
        # PRD §7.2: every proxy must say what it stands in for.
        if self.is_proxy and not self.proxy_for:
            raise ValueError("proxy KPIs must set proxy_for")
        return self


class GroupKpis(_Strict):
    """KPI weights for one position group."""

    weights: dict[str, float]
    # Shown wherever the group's ratings appear when its free metrics are limited (e.g. GK).
    caveat: str | None = None


class TeamMetricDef(_Strict):
    """A team season rate built from one ``fact_team_match`` column."""

    label: str
    source: Source
    column: TeamMatchColumn
    # ``per90``: season total per 90 minutes (counting stats, PRD §8.1). ``match_mean``:
    # mean of per-match values, for ratios such as PPDA that cannot be summed.
    aggregate: Literal["per90", "match_mean"]


class TeamKpiDef(TeamMetricDef):
    """Team-level KPI with the position groups a team need maps to (PRD §8.8 step 7)."""

    higher_is_better: bool
    responsible_groups: list[PositionGroup] = Field(min_length=1)


class StyleFeatureDef(TeamMetricDef):
    """One dimension of a team's style vector for StyleFit (PRD §8.9)."""

    # Divide by another style feature's raw value (e.g. deep completions per possession
    # share as a directness proxy).
    divide_by: str | None = None


class KpiCatalogue(_Strict):
    """Contents of ``config/kpis.yaml``."""

    def_activity_includes_cbi_groups: list[PositionGroup] = Field(default_factory=list)
    kpis: dict[str, KpiDef]
    position_groups: dict[PositionGroup, GroupKpis]
    team_kpis: dict[str, TeamKpiDef]
    style_features: dict[str, StyleFeatureDef] = Field(min_length=2)

    @model_validator(mode="after")
    def _style_divisors_valid(self) -> KpiCatalogue:
        for name, feature in self.style_features.items():
            divisor = feature.divide_by
            if divisor is None:
                continue
            if divisor == name or divisor not in self.style_features:
                raise ValueError(f"style feature {name}: divide_by must name another feature")
            if self.style_features[divisor].divide_by is not None:
                raise ValueError(f"style feature {name}: divisor {divisor} is itself divided")
        return self

    @model_validator(mode="after")
    def _weights_valid(self) -> KpiCatalogue:
        for group, cfg in self.position_groups.items():
            unknown = set(cfg.weights) - set(self.kpis)
            if unknown:
                raise ValueError(f"{group}: unknown KPI ids {sorted(unknown)}")
            if any(w < 0 for w in cfg.weights.values()):
                raise ValueError(f"{group}: weights must be non-negative")
            total = sum(cfg.weights.values())
            if not math.isclose(total, 1.0, abs_tol=WEIGHT_SUM_TOLERANCE):
                raise ValueError(f"{group}: weights sum to {total}, expected 1.0")
        return self


class ReliabilityConfig(_Strict):
    """Reliability component of FitScore: minutes volume + current availability (PRD §8.9)."""

    full_minutes: float = Field(gt=0.0)
    volume_weight: float = Field(ge=0.0)
    availability_weight: float = Field(ge=0.0)
    # FPL status code -> availability in [0, 1].
    status_availability: dict[str, float]

    @model_validator(mode="after")
    def _valid(self) -> ReliabilityConfig:
        if self.volume_weight + self.availability_weight <= 0:
            raise ValueError("reliability weights must not both be zero")
        bad = {k: v for k, v in self.status_availability.items() if not 0.0 <= v <= 1.0}
        if bad:
            raise ValueError(f"status availability must be within [0, 1]: {bad}")
        return self


class AgeProfileConfig(_Strict):
    """AgeProfile component of FitScore (PRD §8.9)."""

    penalty_per_year: float = Field(gt=0.0)


class FitWeights(_Strict):
    """Contents of ``config/fit_weights.yaml`` (PRD §8.9)."""

    components: dict[
        Literal["need_fill", "role_quality", "reliability", "style_fit", "age_profile"], float
    ]
    upgrade_gate_min_delta: float = Field(ge=0.0)
    peak_age: dict[PositionGroup, tuple[int, int]]
    reliability: ReliabilityConfig
    age_profile: AgeProfileConfig

    @model_validator(mode="after")
    def _valid(self) -> FitWeights:
        if len(self.components) != 5:
            raise ValueError("all five FitScore components must be weighted")
        total = sum(self.components.values())
        if not math.isclose(total, 1.0, abs_tol=WEIGHT_SUM_TOLERANCE):
            raise ValueError(f"FitScore weights sum to {total}, expected 1.0")
        for group, (lo, hi) in self.peak_age.items():
            if lo > hi:
                raise ValueError(f"{group}: peak age window {lo}-{hi} is inverted")
        return self


class PositionsConfig(_Strict):
    """Contents of ``config/positions.yaml`` (PRD §8.5)."""

    groups: list[PositionGroup]
    transfermarkt: dict[str, PositionGroup]
    fpl_element_type_fallback: dict[Literal["GKP", "DEF", "MID", "FWD"], PositionGroup]


class TeamAliases(_Strict):
    """Contents of ``config/team_aliases.yaml``."""

    aliases: dict[str, list[str]]

    @model_validator(mode="after")
    def _unique(self) -> TeamAliases:
        seen: dict[str, str] = {}
        for canonical, alts in self.aliases.items():
            for name in [canonical, *alts]:
                key = name.casefold()
                if key in seen and seen[key] != canonical:
                    raise ValueError(f"alias {name!r} maps to both {seen[key]!r} and {canonical!r}")
                seen[key] = canonical
        return self


class AppConfig(_Strict):
    """All validated YAML config."""

    settings: EngineSettings
    kpis: KpiCatalogue
    fit_weights: FitWeights
    positions: PositionsConfig
    team_aliases: TeamAliases


_FILES: dict[str, type[BaseModel]] = {
    "settings": EngineSettings,
    "kpis": KpiCatalogue,
    "fit_weights": FitWeights,
    "positions": PositionsConfig,
    "team_aliases": TeamAliases,
}


def _read_yaml(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


def load_config(config_dir: Path) -> AppConfig:
    """Load and validate every YAML file in ``config_dir``.

    Args:
        config_dir: Directory containing the five config files.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: If a file is missing, is not valid YAML, or fails validation.
    """
    parsed: dict[str, BaseModel] = {}
    for name, model in _FILES.items():
        path = config_dir / f"{name}.yaml"
        try:
            parsed[name] = model.model_validate(_read_yaml(path))
        except ValidationError as exc:
            raise ConfigError(f"invalid config {path.name}: {exc}") from exc
    return AppConfig.model_validate(parsed)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide environment settings."""
    return Settings()


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return process-wide validated YAML config from ``Settings.config_dir``."""
    return load_config(get_settings().config_dir)
