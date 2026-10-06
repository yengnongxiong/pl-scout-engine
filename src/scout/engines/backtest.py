"""Backtest: did last season's diagnosis point at the positions clubs went on to sign?

PRD §8.11 and US-16 (exploratory; clubs sign players for many reasons). For the last
completed season ``S``:

1. Recompute the features as they stood at the end of ``S``: ``S`` plays the part of the
   current season and ``S-1`` the previous one, with the same per-90, blending, shrinkage,
   possession adjustment and percentiles as the live engine (``features.materialise``).
   Past FPL seasons are stored under the ``vaastav`` source, so ``S``'s rows are relabelled
   as the current FPL source first.
2. Diagnose every club of ``S`` against the default benchmark built from ``S``'s own table
   (at the end of ``S`` it is the last completed season) and take its top-n needs (groups
   with a shortfall, most severe first).
3. **Arrivals** are this season's players who have played for a club they had no FPL
   record with in ``S``: signings and loans from inside or outside the league. Their
   position groups are the outcome.
4. **precision@n** per club = share of its top-n needs that match an arrival's group,
   averaged over clubs with at least one arrival. Two baselines: the n most-signed groups
   across the *other* clubs (leave-one-club-out), and the expected precision of n random
   groups.

Promoted clubs (no season ``S`` in the league) and relegated clubs (no arrivals here) are
counted as skipped, never guessed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Engine, select

from scout.config import AppConfig
from scout.db.models import DimPlayer, DimTeam
from scout.db.queries import defensive_padj_totals, player_season_totals, standings
from scout.db.session import make_session_factory
from scout.engines.benchmark import Benchmark, benchmark_clubs
from scout.engines.diagnosis import assess_groups, group_scores, season_context
from scout.errors import ConfigError, NotFoundError
from scout.features.materialise import compute_features
from scout.features.possession import EVEN_SHARE
from scout.ingest.history import previous_seasons

CURRENT_FPL = "fpl"
HISTORY_FPL = "vaastav"
BLENDED = "blended"


@dataclass(frozen=True)
class Arrival:
    """A player who joined a club for this season and has played for it."""

    player_id: int
    player_name: str
    position_group: str | None
    minutes: float


@dataclass(frozen=True)
class PredictedNeed:
    """One of a club's top needs at the end of the backtest season."""

    position_group: str
    severity: float


@dataclass(frozen=True)
class ClubBacktest:
    """Predicted needs vs actual arrivals for one club."""

    team_id: int
    team_name: str
    predicted: list[PredictedNeed]
    arrivals: list[Arrival]
    hits: list[str]
    precision: float | None
    baseline_groups: list[str]
    baseline_precision: float | None
    random_precision: float | None


@dataclass
class BacktestResult:
    """The whole backtest with its receipts."""

    as_of_season: str
    signing_season: str
    benchmark: str
    top_n: int
    clubs: list[ClubBacktest]
    precision: float | None
    baseline_precision: float | None
    random_precision: float | None
    hit_rate: float | None
    evaluated: int
    skipped: dict[str, int] = field(default_factory=dict)
    history_as_of: str | None = None
    arrivals_as_of: str | None = None


def relabel_season(frame: pd.DataFrame, season: str) -> pd.DataFrame:
    """Treat ``season``'s FPL history rows as the current FPL source."""
    out = frame.copy()
    mask = (out["season_id"] == season) & (out["source"] == HISTORY_FPL)
    out.loc[mask, "source"] = CURRENT_FPL
    return out


def club_minutes(
    totals: pd.DataFrame, season: str, source: str, groups: Mapping[int, str | None]
) -> pd.DataFrame:
    """``team_id, player_id, position_group, minutes`` for one season and source."""
    rows = totals[(totals["season_id"] == season) & (totals["source"] == source)]
    out = rows.groupby(["team_id", "player_id"], as_index=False)["minutes"].sum()
    out["position_group"] = [groups.get(int(p)) for p in out["player_id"]]
    out["minutes"] = out["minutes"].fillna(0.0).astype(float)
    known: pd.DataFrame = out[out["position_group"].notna()]
    return known.reset_index(drop=True)


def find_arrivals(
    totals: pd.DataFrame,
    *,
    previous: str,
    current: str,
    groups: Mapping[int, str | None],
    names: Mapping[int, str],
    min_minutes: float,
) -> dict[int, list[Arrival]]:
    """This season's players at a club they had no FPL record with last season."""
    before = totals[(totals["season_id"] == previous) & (totals["source"] == HISTORY_FPL)]
    known = {(int(p), int(t)) for p, t in zip(before["player_id"], before["team_id"], strict=True)}
    now = totals[(totals["season_id"] == current) & (totals["source"] == CURRENT_FPL)]
    played = now.groupby(["team_id", "player_id"], as_index=False)["minutes"].sum()
    out: dict[int, list[Arrival]] = {}
    for team, player, minutes in zip(
        played["team_id"], played["player_id"], played["minutes"], strict=True
    ):
        mins = 0.0 if pd.isna(minutes) else float(minutes)
        if (int(player), int(team)) in known or mins < min_minutes:
            continue
        out.setdefault(int(team), []).append(
            Arrival(int(player), names.get(int(player), str(player)), groups.get(int(player)), mins)
        )
    for arrivals in out.values():
        arrivals.sort(key=lambda a: (-a.minutes, a.player_id))
    return out


def precision(predicted: Sequence[str], actual: set[str]) -> float | None:
    """Share of predicted groups that were signed (``None`` with nothing predicted)."""
    if not predicted:
        return None
    return sum(1 for g in predicted if g in actual) / len(predicted)


def most_signed(
    arrivals: Mapping[int, Sequence[Arrival]], *, exclude: int, n: int, order: Sequence[str]
) -> list[str]:
    """The n most frequent arrival groups across the other clubs (ties in config order)."""
    counts: Counter[str] = Counter(
        a.position_group
        for team, items in arrivals.items()
        if team != exclude
        for a in items
        if a.position_group is not None
    )
    ranked = sorted(counts, key=lambda g: (-counts[g], order.index(g) if g in order else 99))
    return ranked[:n]


def _mean(values: Sequence[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def _newest(frame: pd.DataFrame) -> str | None:
    if frame.empty or "fetched_at" not in frame:
        return None
    known = frame["fetched_at"].dropna()
    return str(known.max()) if not known.empty else None


def run_backtest(engine: Engine, config: AppConfig, *, top_n: int | None = None) -> BacktestResult:
    """Backtest last season's diagnosis against this season's arrivals.

    Raises:
        NotFoundError: If last season's FPL history is not in the warehouse.
    """
    cfg = config.settings.backtest
    n = top_n or cfg.top_n
    method = config.settings.methodology
    ctx = season_context(engine)
    season, before = ctx.previous, previous_seasons(ctx.previous, 1)[0]
    totals = player_season_totals(engine)
    history = totals[(totals["season_id"] == season) & (totals["source"] == HISTORY_FPL)]
    if history.empty:
        raise NotFoundError(
            f"no FPL history for {season}; run `scout ingest --source vaastav` and `scout build`",
            details={"season": season},
        )
    with make_session_factory(engine)() as session:
        players = list(session.scalars(select(DimPlayer)))
        team_names = {t.team_id: t.name for t in session.scalars(select(DimTeam))}
    groups = {p.player_id: p.position_group for p in players}
    names = {p.player_id: p.canonical_name for p in players}

    padj = defensive_padj_totals(
        engine,
        even_share=EVEN_SHARE,
        clip_min=method.possession_multiplier_min,
        clip_max=method.possession_multiplier_max,
    )
    features = compute_features(
        relabel_season(totals, season),
        relabel_season(padj, season),
        groups,
        current_season=season,
        previous_season=before,
        catalogue=config.kpis,
        method=method,
    )
    pct = (
        features[features["season_mode"] == BLENDED][["player_id", "kpi", "percentile"]]
        if not features.empty
        else pd.DataFrame(columns=["player_id", "kpi", "percentile"])
    )
    squads = club_minutes(relabel_season(totals, season), season, CURRENT_FPL, groups)
    scores = group_scores(squads, pct)
    table = standings(engine, season)
    benchmark: Benchmark = config.settings.diagnosis.default_benchmark
    if benchmark == "custom":
        benchmark = "top6"
    sizes = {str(k): v for k, v in config.settings.diagnosis.benchmark_sizes.items()}
    league = [int(t) for t in table["team_id"]]

    arrivals = find_arrivals(
        totals,
        previous=season,
        current=ctx.current,
        groups=groups,
        names=names,
        min_minutes=cfg.arrival_min_minutes,
    )
    order = list(config.kpis.position_groups)
    skipped: Counter[str] = Counter()
    skipped["promoted (no diagnosis)"] = len(set(ctx.team_names) - set(league))
    clubs: list[ClubBacktest] = []
    for team in sorted(league, key=lambda t: team_names.get(t, str(t))):
        if team not in ctx.team_names:
            skipped["relegated (no arrivals)"] += 1
            continue
        try:
            bench = benchmark_clubs(
                table, benchmark, club_id=team, sizes=sizes, league_clubs=league
            )
        except ConfigError:
            skipped["no benchmark"] += 1
            continue
        assessed = assess_groups(team, bench, scores, config.kpis)
        predicted = [
            PredictedNeed(a.position_group, a.severity) for a in assessed if a.severity > 0
        ][:n]
        signed = arrivals.get(team, [])
        actual = {a.position_group for a in signed if a.position_group is not None}
        predicted_groups = [p.position_group for p in predicted]
        baseline = most_signed(arrivals, exclude=team, n=n, order=order)
        evaluable = bool(actual) and bool(predicted)
        if not actual:
            skipped["no arrivals yet"] += 1
        elif not predicted:
            skipped["no shortfall vs benchmark"] += 1
        clubs.append(
            ClubBacktest(
                team_id=team,
                team_name=team_names.get(team, str(team)),
                predicted=predicted,
                arrivals=signed,
                hits=[g for g in predicted_groups if g in actual],
                precision=precision(predicted_groups, actual) if evaluable else None,
                baseline_groups=baseline,
                baseline_precision=precision(baseline, actual) if evaluable else None,
                random_precision=len(actual) / len(order) if evaluable else None,
            )
        )
    evaluated = [c for c in clubs if c.precision is not None]
    current_rows = totals[(totals["season_id"] == ctx.current) & (totals["source"] == CURRENT_FPL)]
    return BacktestResult(
        as_of_season=season,
        signing_season=ctx.current,
        benchmark=benchmark,
        top_n=n,
        clubs=clubs,
        precision=_mean([c.precision for c in evaluated]),
        baseline_precision=_mean([c.baseline_precision for c in evaluated]),
        random_precision=_mean([c.random_precision for c in evaluated]),
        hit_rate=_mean([1.0 if c.hits else 0.0 for c in evaluated]),
        evaluated=len(evaluated),
        skipped={k: v for k, v in sorted(skipped.items()) if v},
        history_as_of=_newest(history),
        arrivals_as_of=_newest(current_rows),
    )
