"""Materialise ``player_season_features`` from warehouse totals (PRD §8.1-8.7).

For every player, KPI in ``config/kpis.yaml`` and season mode:

1. **Totals per season** come from the KPI's source: FPL KPIs use this season's ``fpl``
   rows and last season's ``vaastav`` rows; Understat KPIs use ``understat`` rows. Rows
   are summed across clubs (a player's rating covers all their minutes); per-90 uses
   that source's own minutes.
2. **Per 90** (§8.1), then **blend** with last season (§8.2) in ``blended`` mode, or the
   current season alone in ``current`` mode.
3. **Shrink** toward the minutes-weighted mean of the player's position group (§8.3).
4. **Percentiles** of shrunk values among players meeting the minutes threshold (§8.6),
   with ``n_peers`` always present.

Defensive KPIs use possession-adjusted totals (§8.4) and record whether every match was
adjusted. Each row keeps its source and the newest ``fetched_at`` behind it (rule 3).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import Engine, select

from scout.config import AppConfig, KpiCatalogue, MethodologyConfig
from scout.db.load import replace_player_season_features
from scout.db.models import DimPlayer, DimSeason
from scout.db.queries import defensive_padj_totals, player_season_totals
from scout.db.session import make_session_factory
from scout.errors import ConfigError, SourceUnavailableError
from scout.features.blend import blend
from scout.features.per90 import per90
from scout.features.percentiles import percentiles
from scout.features.possession import EVEN_SHARE
from scout.features.shrinkage import shrink
from scout.ingest.history import previous_seasons

SEASON_MODES = ("blended", "current")
PREVIOUS_SEASON_SOURCE = {"fpl": "vaastav", "understat": "understat"}

Row = Mapping[str, Any]


@dataclass(frozen=True)
class KpiFormula:
    """How to compute one KPI from a player's season totals."""

    numerator: Callable[[Row, Row, bool], float | None]
    uses_padj: bool = False
    per_90: bool = True
    denominator: Callable[[Row], float | None] | None = None


def _get(row: Row, key: str) -> float | None:
    value = row.get(key)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _sum(*values: float | None) -> float | None:
    if any(v is None for v in values):
        return None
    return float(sum(v for v in values if v is not None))


def _def_activity(_: Row, padj: Row, include_cbi: bool) -> float | None:
    parts = [_get(padj, "tackles_padj"), _get(padj, "recoveries_padj")]
    if include_cbi:
        parts.append(_get(padj, "cbi_padj"))
    return _sum(*parts)


def _goals_minus_xg(t: Row, _p: Row, _c: bool) -> float | None:
    goals, xg = _get(t, "goals"), _get(t, "xg")
    return None if goals is None or xg is None else goals - xg


def _total(column: str) -> Callable[[Row, Row, bool], float | None]:
    return lambda t, _p, _c: _get(t, column)


def _padj(column: str) -> Callable[[Row, Row, bool], float | None]:
    return lambda _t, p, _c: _get(p, column)


FORMULAS: dict[str, KpiFormula] = {
    "def_activity_padj_p90": KpiFormula(_def_activity, uses_padj=True),
    "cbi_padj_p90": KpiFormula(_padj("cbi_padj"), uses_padj=True),
    "recoveries_padj_p90": KpiFormula(_padj("recoveries_padj"), uses_padj=True),
    "tackles_padj_p90": KpiFormula(_padj("tackles_padj"), uses_padj=True),
    "xgc_on_pitch_p90": KpiFormula(_total("xgc_on_pitch")),
    "cards_p90": KpiFormula(lambda t, _p, _c: _sum(_get(t, "yellow_cards"), _get(t, "red_cards"))),
    "xg_buildup_p90": KpiFormula(_total("xg_buildup")),
    "xg_chain_p90": KpiFormula(_total("xg_chain")),
    "xa_p90": KpiFormula(_total("xa")),
    "npxg_p90": KpiFormula(_total("npxg")),
    "key_passes_p90": KpiFormula(_total("key_passes")),
    "shots_p90": KpiFormula(_total("shots")),
    "goals_minus_xg_p90": KpiFormula(_goals_minus_xg),
    # Shot quality is a ratio, not a rate: npxG per shot.
    "npxg_per_shot": KpiFormula(
        _total("npxg"), per_90=False, denominator=lambda t: _get(t, "shots")
    ),
}


@dataclass(frozen=True)
class SeasonInput:
    """One player's totals for one season and source."""

    totals: Row
    padj: Row
    minutes: float


def _rate(formula: KpiFormula, season: SeasonInput | None, include_cbi: bool) -> float | None:
    if season is None:
        return None
    numerator = formula.numerator(season.totals, season.padj, include_cbi)
    if formula.per_90:
        return per90(numerator, season.minutes)
    assert formula.denominator is not None
    denominator = formula.denominator(season.totals)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _padj_status(seasons: list[SeasonInput]) -> str:
    matches = sum(int(_get(s.padj, "matches") or 0) for s in seasons)
    unadjusted = sum(int(_get(s.padj, "unadjusted_matches") or 0) for s in seasons)
    if matches == 0 or unadjusted == matches:
        return "unadjusted"
    return "adjusted" if unadjusted == 0 else "partial"


def _collapse_clubs(frame: pd.DataFrame) -> dict[tuple[int, str, str], dict[str, Any]]:
    """Sum club rows into one row per (player, season, source); keep newest fetched_at."""
    out: dict[tuple[int, str, str], dict[str, Any]] = {}
    for rec in frame.to_dict(orient="records"):
        key = (int(rec["player_id"]), str(rec["season_id"]), str(rec["source"]))
        acc = out.setdefault(key, {})
        for col, value in rec.items():
            col = str(col)
            if col in ("player_id", "season_id", "source", "team_id"):
                continue
            if col == "fetched_at":
                if value is not None and not pd.isna(value):
                    acc[col] = max(acc[col], value) if acc.get(col) is not None else value
                continue
            number = None if value is None or pd.isna(value) else float(value)
            if number is None:
                acc.setdefault(col, None)
            else:
                acc[col] = (acc.get(col) or 0.0) + number
    return out


def compute_features(
    totals: pd.DataFrame,
    padj: pd.DataFrame,
    position_groups: Mapping[int, str | None],
    *,
    current_season: str,
    previous_season: str,
    catalogue: KpiCatalogue,
    method: MethodologyConfig,
) -> pd.DataFrame:
    """Compute the long-format feature table (one row per player x mode x KPI)."""
    unknown = sorted(set(catalogue.kpis) - set(FORMULAS))
    if unknown:
        raise ConfigError(f"no formula for KPI(s) {unknown}; add them to features/materialise.py")
    season_totals = _collapse_clubs(totals)
    season_padj = _collapse_clubs(padj)
    cbi_groups = set(catalogue.def_activity_includes_cbi_groups)

    rows: list[dict[str, Any]] = []
    for player_id, group in position_groups.items():
        if group is None:
            continue  # goalkeepers / unknown positions are out of scope (PRD §8.5)
        for kpi_id, kpi in catalogue.kpis.items():
            formula = FORMULAS[kpi_id]
            seasons: dict[str, SeasonInput | None] = {}
            as_of: list[datetime] = []
            for label, season_id, source in (
                ("cur", current_season, kpi.source),
                ("prev", previous_season, PREVIOUS_SEASON_SOURCE.get(kpi.source, kpi.source)),
            ):
                key = (player_id, season_id, source)
                t = season_totals.get(key)
                if t is None:
                    seasons[label] = None
                    continue
                p = season_padj.get(key, {})
                seasons[label] = SeasonInput(t, p, float(t.get("minutes") or 0.0))
                if t.get("fetched_at") is not None:
                    as_of.append(pd.Timestamp(t["fetched_at"]).to_pydatetime())
            include_cbi = group in cbi_groups
            cur, prev = seasons["cur"], seasons["prev"]
            r_cur = _rate(formula, cur, include_cbi)
            r_prev = _rate(formula, prev, include_cbi)
            used = [s for s in (cur, prev) if s is not None]
            padj_status = _padj_status(used) if formula.uses_padj else None
            for mode in SEASON_MODES:
                if mode == "blended":
                    b = blend(
                        r_cur,
                        cur.minutes if cur else 0.0,
                        r_prev,
                        prev.minutes if prev else 0.0,
                        lam=method.blend_lambda,
                        prev_minutes_cap=method.prev_season_minutes_cap,
                    )
                    value, eff_minutes, used_prev = b.rate, b.minutes, b.used_previous
                else:
                    value = r_cur
                    eff_minutes = cur.minutes if cur and r_cur is not None else 0.0
                    used_prev = False
                rows.append(
                    {
                        "player_id": player_id,
                        "season_mode": mode,
                        "position_group": group,
                        "kpi": kpi_id,
                        "source": kpi.source,
                        "raw_p90": r_cur,
                        "value": value,
                        "minutes": cur.minutes if cur else 0.0,
                        "effective_minutes": eff_minutes,
                        "used_previous_season": used_prev,
                        "is_proxy": kpi.is_proxy,
                        "padj_status": padj_status,
                        "as_of": max(as_of) if as_of else None,
                        "higher_is_better": kpi.higher_is_better,
                        "shrinkage_k": kpi.shrinkage_k or method.default_shrinkage_k,
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = _add_shrunk(frame)
    return _add_percentiles(frame, method.percentile_min_minutes)


def _add_shrunk(frame: pd.DataFrame) -> pd.DataFrame:
    """Shrink toward the minutes-weighted group mean of each (mode, group, KPI)."""
    sums: dict[tuple[str, str, str], tuple[float, float]] = {}
    for mode, group, kpi, value, minutes in zip(
        frame["season_mode"],
        frame["position_group"],
        frame["kpi"],
        frame["value"],
        frame["effective_minutes"],
        strict=True,
    ):
        key = (str(mode), str(group), str(kpi))
        weighted, weight = sums.get(key, (0.0, 0.0))
        if not pd.isna(value) and float(minutes) > 0:
            weighted, weight = weighted + float(value) * float(minutes), weight + float(minutes)
        sums[key] = (weighted, weight)
    priors = {key: (w / m if m > 0 else None) for key, (w, m) in sums.items()}
    frame["shrunk"] = [
        shrink(
            None if pd.isna(v) else float(v),
            float(m),
            priors[(str(mode), str(g), str(k))],
            float(kk),
        )
        for v, m, mode, g, k, kk in zip(
            frame["value"],
            frame["effective_minutes"],
            frame["season_mode"],
            frame["position_group"],
            frame["kpi"],
            frame["shrinkage_k"],
            strict=True,
        )
    ]
    return frame


def _add_percentiles(frame: pd.DataFrame, min_minutes: float) -> pd.DataFrame:
    """Percentile of shrunk values per mode; ``n_peers`` for every row in the group."""
    parts = []
    for mode, grp in frame.groupby("season_mode"):
        ranked = percentiles(
            grp.rename(columns={"shrunk": "value", "value": "blended_value"})[
                ["player_id", "position_group", "kpi", "value", "effective_minutes",
                 "higher_is_better"]
            ].rename(columns={"effective_minutes": "minutes"}),
            min_minutes=min_minutes,
        )  # fmt: skip
        ranked = ranked[["player_id", "kpi", "percentile", "n_peers"]].assign(season_mode=mode)
        parts.append(ranked)
    ranks = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    out = frame.merge(ranks, on=["player_id", "kpi", "season_mode"], how="left")
    peers = out.groupby(["season_mode", "position_group", "kpi"])["n_peers"].transform("max")
    out["n_peers"] = peers.fillna(0).astype(int)
    return out.drop(columns=["higher_is_better", "shrinkage_k"])


def materialise_features(engine: Engine, config: AppConfig) -> int:
    """Compute features from the warehouse and replace ``player_season_features``."""
    with make_session_factory(engine)() as session:
        current = session.scalars(select(DimSeason.season_id).where(DimSeason.is_current)).first()
        if current is None:
            raise SourceUnavailableError("no current season in the warehouse; run `scout build`")
        groups = {p.player_id: p.position_group for p in session.scalars(select(DimPlayer))}
    method = config.settings.methodology
    totals = player_season_totals(engine)
    padj = defensive_padj_totals(
        engine,
        even_share=EVEN_SHARE,
        clip_min=method.possession_multiplier_min,
        clip_max=method.possession_multiplier_max,
    )
    frame = compute_features(
        totals,
        padj,
        groups,
        current_season=current,
        previous_season=previous_seasons(current, 1)[0],
        catalogue=config.kpis,
        method=method,
    )
    with make_session_factory(engine)() as session, session.begin():
        return replace_player_season_features(session, frame)
