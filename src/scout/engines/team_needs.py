"""Team-level needs (PRD §8.8 step 7).

Team KPIs (xG for and against, PPDA, deep completions, set-piece xG...) describe how a
side plays as a whole, so no single player owns them. Each KPI becomes a season rate, is
ranked against the rest of the league (higher percentile always better, inverse KPIs
flipped as in PRD §8.6), and compared with the benchmark clubs' mean percentile. A
shortfall is a team-level need, mapped to the position groups most responsible for it
(``responsible_groups`` in ``config/kpis.yaml``).

Rates: counting stats are per 90 (PRD §8.1; a team plays 90 minutes a match). Ratios
such as PPDA are the mean of per-match values, because a ratio of season totals needs
the raw pass and defensive-action counts, which the source does not provide. In blended
mode the current season is blended with the previous one exactly like player rates
(PRD §8.2), weighting each season by team minutes (matches with data x 90), so early in
the season last year's profile dominates and fades as matches are played.

Team needs add context to the position-group needs; they do not change group severity,
which stays the weighted player-KPI shortfall of steps 1-3.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import Engine

from scout.config import AppConfig, TeamKpiDef
from scout.db.queries import team_season_totals
from scout.features.blend import blend
from scout.features.per90 import MINUTES_PER_MATCH, per90
from scout.features.percentiles import PERCENT, percent_rank

VALUE_COLUMNS = [
    "team_id", "kpi", "value", "matches", "previous_matches", "effective_minutes", "source",
    "as_of",
]  # fmt: skip


@dataclass(frozen=True)
class TeamNeed:
    """A team KPI where the club trails the benchmark, with its receipt (rule 3)."""

    kpi: str
    label: str
    higher_is_better: bool
    club_value: float
    club_percentile: float
    benchmark_value: float
    benchmark_percentile: float
    gap: float
    n_peers: int
    benchmark_clubs: int
    matches: int
    previous_matches: int
    responsible_groups: tuple[str, ...]
    source: str
    as_of: str | None


def _opt_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(str(value))


def season_rate(
    row: Mapping[Hashable, Any] | None, kpi: TeamKpiDef
) -> tuple[float | None, int, object]:
    """One season's rate for ``kpi`` from a ``team_season.sql`` row.

    Returns:
        ``(rate, matches with data, as_of)``; the rate is ``None`` when no match has
        data (never 0, CLAUDE.md rule 2).
    """
    if row is None:
        return None, 0, None
    total = _opt_float(row[f"{kpi.column}_total"])
    matches = int(row[f"{kpi.column}_matches"] or 0)
    if total is None or matches <= 0:
        return None, 0, None
    if kpi.aggregate == "per90":
        rate = per90(total, matches * MINUTES_PER_MATCH)
    else:
        rate = total / matches
    return rate, matches, row["as_of"]


def _newest(values: Sequence[Any]) -> str | None:
    stamps = [pd.Timestamp(str(v)) for v in values if v is not None and not pd.isna(v)]
    return max(stamps).isoformat() if stamps else None


def team_kpi_values(
    totals: pd.DataFrame,
    team_kpis: Mapping[str, TeamKpiDef],
    *,
    current: str,
    previous: str | None,
    lam: float,
    prev_minutes_cap: float,
) -> pd.DataFrame:
    """Season (or blended) rate per club and team KPI.

    Args:
        totals: ``team_season.sql`` rows with a ``source`` column.
        team_kpis: Team KPI definitions (config).
        current: Current season id.
        previous: Previous season id to blend in, or ``None`` for current-season mode.
        lam: Blending weight λ (config ``blend_lambda``, PRD §8.2).
        prev_minutes_cap: Cap on previous-season minutes (config).

    Returns:
        ``team_id, kpi, value, matches, previous_matches, effective_minutes, source,
        as_of``; clubs with no data for a KPI get no row.
    """
    index: dict[tuple[str, int, str], dict[Hashable, Any]] = {
        (str(r["source"]), int(r["team_id"]), str(r["season_id"])): r
        for r in totals.to_dict(orient="records")
    }
    teams = sorted({team for _, team, _ in index})
    rows: list[dict[str, object]] = []
    for kpi_id, kpi in team_kpis.items():
        for team in teams:
            cur_rate, cur_n, cur_as_of = season_rate(index.get((kpi.source, team, current)), kpi)
            prev_row = index.get((kpi.source, team, previous)) if previous else None
            prev_rate, prev_n, prev_as_of = season_rate(prev_row, kpi)
            blended = blend(
                cur_rate,
                cur_n * MINUTES_PER_MATCH,
                prev_rate,
                prev_n * MINUTES_PER_MATCH,
                lam=lam,
                prev_minutes_cap=prev_minutes_cap,
            )
            if blended.rate is None:
                continue
            rows.append(
                {
                    "team_id": team,
                    "kpi": kpi_id,
                    "value": blended.rate,
                    "matches": cur_n,
                    "previous_matches": prev_n if blended.used_previous else 0,
                    "effective_minutes": blended.minutes,
                    "source": kpi.source,
                    "as_of": _newest([cur_as_of, prev_as_of if blended.used_previous else None]),
                }
            )
    return pd.DataFrame(rows, columns=VALUE_COLUMNS)


def team_percentiles(
    values: pd.DataFrame, league_ids: Sequence[int], team_kpis: Mapping[str, TeamKpiDef]
) -> pd.DataFrame:
    """League percentile (0-100, higher always better) and ``n_peers`` per KPI.

    Only clubs in ``league_ids`` (this season's league) are ranked, with the same
    ``PERCENT_RANK`` semantics as player percentiles (PRD §8.6).
    """
    ranked = values[values["team_id"].isin(list(league_ids))].copy()
    if ranked.empty:
        return ranked.assign(percentile=pd.Series(dtype=float), n_peers=pd.Series(dtype=int))
    higher = ranked["kpi"].map(lambda k: team_kpis[str(k)].higher_is_better).astype(bool)
    ranked["score"] = ranked["value"].where(higher, -ranked["value"])
    ranked["percentile"] = (
        ranked.groupby("kpi", group_keys=False)["score"].apply(percent_rank) * PERCENT
    )
    ranked["n_peers"] = ranked.groupby("kpi")["score"].transform("size")
    return ranked.drop(columns=["score"])


def assess_team(
    club_id: int,
    benchmark_ids: Sequence[int],
    ranked: pd.DataFrame,
    team_kpis: Mapping[str, TeamKpiDef],
) -> list[TeamNeed]:
    """Team KPIs where the club's percentile trails the benchmark mean, biggest gap first.

    KPIs where the club or every benchmark club lacks data are skipped: no evidence, no
    need. Being ahead of the benchmark is not a need.
    """
    by_key: dict[tuple[str, int], dict[Hashable, Any]] = {
        (str(r["kpi"]), int(r["team_id"])): r for r in ranked.to_dict(orient="records")
    }
    out: list[TeamNeed] = []
    for kpi_id, kpi in team_kpis.items():
        club = by_key.get((kpi_id, club_id))
        bench = [r for b in benchmark_ids if (r := by_key.get((kpi_id, b))) is not None]
        if club is None or not bench:
            continue
        bench_pct = sum(float(r["percentile"]) for r in bench) / len(bench)
        gap = bench_pct - float(club["percentile"])
        if gap <= 0:
            continue
        out.append(
            TeamNeed(
                kpi=kpi_id,
                label=kpi.label,
                higher_is_better=kpi.higher_is_better,
                club_value=float(club["value"]),
                club_percentile=float(club["percentile"]),
                benchmark_value=sum(float(r["value"]) for r in bench) / len(bench),
                benchmark_percentile=bench_pct,
                gap=gap,
                n_peers=int(club["n_peers"]),
                benchmark_clubs=len(bench),
                matches=int(club["matches"]),
                previous_matches=int(club["previous_matches"]),
                responsible_groups=tuple(kpi.responsible_groups),
                source=str(club["source"]),
                as_of=_newest([club["as_of"], *(r["as_of"] for r in bench)]),
            )
        )
    return sorted(out, key=lambda n: (-n.gap, n.kpi))


def team_level_needs(
    engine: Engine,
    club_id: int,
    benchmark_ids: Sequence[int],
    league_ids: Sequence[int],
    config: AppConfig,
    *,
    current: str,
    previous: str | None,
) -> list[TeamNeed]:
    """Team-level needs for ``club_id`` from the warehouse (PRD §8.8 step 7).

    Args:
        engine: Warehouse engine.
        club_id: Club being diagnosed.
        benchmark_ids: Benchmark clubs (``benchmark_clubs``).
        league_ids: This season's league clubs, the percentile peer set.
        config: App config (team KPIs, blending settings).
        current: Current season id.
        previous: Previous season to blend in (blended mode), or ``None`` (current mode).
    """
    team_kpis = config.kpis.team_kpis
    sources = sorted({k.source for k in team_kpis.values()})
    frames = [team_season_totals(engine, s).assign(source=s) for s in sources]
    totals = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if totals.empty:
        return []
    method = config.settings.methodology
    values = team_kpi_values(
        totals,
        team_kpis,
        current=current,
        previous=previous,
        lam=method.blend_lambda,
        prev_minutes_cap=method.prev_season_minutes_cap,
    )
    ranked = team_percentiles(values, league_ids, team_kpis)
    return assess_team(club_id, benchmark_ids, ranked, team_kpis)
