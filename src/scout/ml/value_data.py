"""Training and scoring data for the stats-implied market value model (PRD §8.10 step 3).

One row per player-season: the player's season totals summed over every club they played
for (the club with the most minutes is their club for the season), turned into the model's
features, plus a label for completed seasons:

- **age** at the season's last kickoff; **position group**;
- **minutes** and **minutes share** (minutes / (club matches x 90)), how much the player
  actually played;
- **per-90 rates** of the counting stats listed in config (a stat missing for a season,
  such as FPL expected goals before 2022-23, stays missing: never 0, CLAUDE.md rule 2),
  **blended** with the player's previous season exactly as everywhere else (PRD §8.2), so
  training rows and this season's part-season rows are built the same way;
- **club points per game** that season, a team-strength proxy.

The label is the Transfermarkt estimated market value nearest the season's last kickoff
within a configured window (Transfermarkt revalues the league around the end of each
season), kept with its own as-of date and source as the receipt.

Scoring rows (``scoring_frame``) are this season's players with the same features, age on
the date of their current Transfermarkt value, and that value's receipt.

Limitation (shown in ``docs/EVALUATION.md``): the warehouse holds only players in this
season's FPL game, so training rows are past seasons of players still in the league —
players who dropped out are missing (survivorship bias).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import Engine, select

from scout.config import AppConfig, MethodologyConfig, ValueModelConfig
from scout.db.models import DimPlayer, DimSeason
from scout.db.queries import (
    latest_market_values,
    market_value_history,
    player_season_totals,
    season_bounds,
    standings,
)
from scout.db.session import make_session_factory
from scout.engines.recommend import age_on, preferred_market_value
from scout.features.blend import blend
from scout.features.per90 import MINUTES_PER_MATCH, per90
from scout.ingest.history import previous_seasons

logger = logging.getLogger(__name__)

DAYS_PER_YEAR = 365.25
HISTORY_SOURCE = "vaastav"
CURRENT_SOURCE = "fpl"


@dataclass(frozen=True)
class Valuation:
    """A Transfermarkt estimated market value point with its receipt."""

    when: date
    value_eur: int
    source: str


def nearest_valuation(
    points: Sequence[Valuation], target: date, *, before_days: int, after_days: int
) -> Valuation | None:
    """The valuation closest to ``target`` within [target - before, target + after].

    Ties go to the later valuation (it already reflects the finished season).
    """
    best: tuple[tuple[int, int], Valuation] | None = None
    for point in points:
        delta = (point.when - target).days
        if -before_days <= delta <= after_days:
            key = (abs(delta), -delta)
            if best is None or key < best[0]:
                best = (key, point)
    return None if best is None else best[1]


def _num(value: object) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(str(value))


def _sum(values: Sequence[float | None]) -> float | None:
    """Sum of known values; ``None`` when none is known (SQL ``SUM`` semantics)."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def player_seasons(
    totals: pd.DataFrame,
    players: Mapping[int, tuple[str | None, date | None]],
    season_ends: Mapping[str, date],
    club_records: Mapping[str, Mapping[int, tuple[int, int]]],
    *,
    source: str,
    seasons: Sequence[str],
    per90_stats: Sequence[str],
) -> pd.DataFrame:
    """Feature rows per player-season from ``player_season.sql`` totals.

    Args:
        totals: Player x season x club x source totals.
        players: ``player_id -> (position_group, birth_date)``.
        season_ends: Season id -> date of its last kickoff.
        club_records: Season id -> club id -> ``(matches played, points)``.
        source: Totals source to use (``vaastav`` for past seasons, ``fpl`` for this one).
        seasons: Seasons to include.
        per90_stats: Counting stats turned into per-90 features.
    """
    rows = totals[(totals["source"] == source) & totals["season_id"].isin(list(seasons))]
    grouped: dict[tuple[int, str], list[dict[Hashable, Any]]] = {}
    for rec in rows.to_dict(orient="records"):
        grouped.setdefault((int(rec["player_id"]), str(rec["season_id"])), []).append(rec)
    out: list[dict[str, object]] = []
    for (pid, season), clubs in sorted(grouped.items()):
        minutes = _sum([_num(c["minutes"]) for c in clubs]) or 0.0
        main = max(clubs, key=lambda c: (_num(c["minutes"]) or 0.0, -int(c["team_id"])))
        team = int(main["team_id"])
        played, points = club_records.get(season, {}).get(team, (0, 0))
        group, birth = players.get(pid, (None, None))
        end = season_ends.get(season)
        row: dict[str, object] = {
            "player_id": pid,
            "season_id": season,
            "team_id": team,
            "position_group": group,
            "age": None if birth is None or end is None else (end - birth).days / DAYS_PER_YEAR,
            "minutes": minutes,
            "minutes_share": minutes / (played * MINUTES_PER_MATCH) if played else None,
            "team_ppg": points / played if played else None,
            "season_end": end,
            "as_of": max(str(c["fetched_at"]) for c in clubs),
        }
        for stat in per90_stats:
            row[f"{stat}_p90"] = per90(_sum([_num(c[stat]) for c in clubs]), minutes)
        out.append(row)
    return pd.DataFrame(out)


def blend_rates(
    current: pd.DataFrame,
    previous: pd.DataFrame,
    per90_stats: Sequence[str],
    method: MethodologyConfig,
) -> pd.DataFrame:
    """Blend each per-90 rate with the same player's previous season (PRD §8.2).

    ``current`` and ``previous`` are ``player_seasons`` rows for one season each. Minutes
    share and club points per game stay this season's: they are already shares, not
    small-sample counts. Adds ``effective_minutes`` (this season's minutes plus λ x last
    season's, capped) and ``used_previous_season``.
    """
    prev = {int(r["player_id"]): r for r in previous.to_dict(orient="records")}
    lam, cap = method.blend_lambda, method.prev_season_minutes_cap
    rates: dict[str, list[float | None]] = {stat: [] for stat in per90_stats}
    effective: list[float] = []
    used: list[bool] = []
    as_of: list[str] = []
    for rec in current.to_dict(orient="records"):
        p = prev.get(int(rec["player_id"]))
        m_cur = _num(rec["minutes"]) or 0.0
        m_prev = (_num(p["minutes"]) or 0.0) if p is not None else 0.0
        weight_prev = lam * min(m_prev, cap)
        effective.append(m_cur + weight_prev)
        used.append(weight_prev > 0)
        as_of.append(str(rec["as_of"]) if p is None else max(str(rec["as_of"]), str(p["as_of"])))
        for stat in per90_stats:
            col = f"{stat}_p90"
            r_prev = _num(p[col]) if p is not None else None
            b = blend(_num(rec[col]), m_cur, r_prev, m_prev, lam=lam, prev_minutes_cap=cap)
            rates[stat].append(b.rate)
    out = current.copy()
    for stat, values in rates.items():
        out[f"{stat}_p90"] = values
    out["effective_minutes"] = effective
    out["used_previous_season"] = used
    out["as_of"] = as_of
    return out


def attach_labels(
    frame: pd.DataFrame, history: pd.DataFrame, cfg: ValueModelConfig
) -> pd.DataFrame:
    """Add ``value_eur``, ``log_value``, ``value_date`` and ``value_source`` (or None)."""
    points: dict[int, list[Valuation]] = {}
    for rec in history.to_dict(orient="records"):
        points.setdefault(int(rec["player_id"]), []).append(
            Valuation(rec["tm_last_updated"], int(rec["value_eur"]), str(rec["source"]))
        )
    labels: list[Valuation | None] = []
    for pid, end in zip(frame["player_id"], frame["season_end"], strict=True):
        labels.append(
            None
            if end is None
            else nearest_valuation(
                points.get(int(pid), []),
                end,
                before_days=cfg.label_window_days_before,
                after_days=cfg.label_window_days_after,
            )
        )
    out = frame.copy()
    out["value_eur"] = [None if v is None else v.value_eur for v in labels]
    out["log_value"] = [
        None if v is None or v.value_eur <= 0 else math.log(v.value_eur) for v in labels
    ]
    out["value_date"] = [None if v is None else v.when for v in labels]
    out["value_source"] = [None if v is None else v.source for v in labels]
    return out


def _club_records(engine: Engine, seasons: Sequence[str]) -> dict[str, dict[int, tuple[int, int]]]:
    out: dict[str, dict[int, tuple[int, int]]] = {}
    for season in seasons:
        table = standings(engine, season)
        out[season] = {
            int(t): (int(p), int(pts))
            for t, p, pts in zip(table["team_id"], table["played"], table["points"], strict=True)
        }
    return out


def player_context(engine: Engine) -> tuple[str, dict[int, tuple[str | None, date | None]]]:
    """The current season and every player's ``(position group, date of birth)``."""
    with make_session_factory(engine)() as session:
        current = session.scalars(select(DimSeason.season_id).where(DimSeason.is_current)).first()
        players = {
            p.player_id: (p.position_group, p.birth_date)
            for p in session.scalars(select(DimPlayer))
        }
    if current is None:
        raise ValueError("no current season in the warehouse; run `scout build`")
    return current, players


def training_frame(engine: Engine, config: AppConfig) -> pd.DataFrame:
    """Labelled past player-seasons with at least ``min_minutes`` (model training data)."""
    cfg = config.settings.value_model
    current, players = player_context(engine)
    totals = player_season_totals(engine)
    seasons = zip(totals["season_id"], totals["source"], strict=True)
    past = sorted({str(s) for s, src in seasons if src == HISTORY_SOURCE and str(s) != current})
    bounds = season_bounds(engine)
    ends = {
        str(season): pd.Timestamp(last).date()
        for season, last in zip(bounds["season_id"], bounds["last_kickoff"], strict=True)
    }
    rows = player_seasons(
        totals,
        players,
        ends,
        _club_records(engine, past),
        source=HISTORY_SOURCE,
        seasons=past,
        per90_stats=cfg.per90_stats,
    )
    if rows.empty:
        return rows
    method = config.settings.methodology
    frame = pd.concat(
        [
            blend_rates(
                rows[rows["season_id"] == season],
                rows[rows["season_id"] == previous_seasons(season, 1)[0]],
                cfg.per90_stats,
                method,
            )
            for season in past
        ],
        ignore_index=True,
    )
    labelled = attach_labels(frame, market_value_history(engine), cfg)
    keep = labelled["log_value"].notna() & (labelled["minutes"] >= cfg.min_minutes)
    logger.info(
        "value training frame",
        extra={"seasons": past, "rows": int(keep.sum()), "unlabelled": int((~keep).sum())},
    )
    return labelled[keep].reset_index(drop=True)


def scoring_frame(engine: Engine, config: AppConfig) -> pd.DataFrame:
    """This season's players with blended features and their current Transfermarkt value.

    The value is the most preferred source's newest one (``market_value_precedence``) and
    keeps its receipt (``value_date``, ``value_source``, ``value_is_stale``). Age is taken
    on the value's own date, as training ages are taken next to their label. Only players
    with a value, a position group and at least ``min_minutes`` effective (blended) minutes
    are returned; for everyone else the stats-implied value is "Not available".
    """
    cfg = config.settings.value_model
    current, players = player_context(engine)
    previous = previous_seasons(current, 1)[0]
    totals = player_season_totals(engine)
    records = _club_records(engine, [current, previous])

    def season_rows(season: str, source: str) -> pd.DataFrame:
        return player_seasons(
            totals,
            players,
            {},
            records,
            source=source,
            seasons=[season],
            per90_stats=cfg.per90_stats,
        )

    rows = season_rows(current, CURRENT_SOURCE)
    if rows.empty:
        return rows
    frame = blend_rates(
        rows, season_rows(previous, HISTORY_SOURCE), cfg.per90_stats, config.settings.methodology
    )
    values: dict[int, list[dict[Hashable, Any]]] = {}
    for rec in latest_market_values(engine).to_dict(orient="records"):
        values.setdefault(int(rec["player_id"]), []).append(rec)
    precedence = config.settings.recommend.market_value_precedence
    chosen = [
        preferred_market_value(values.get(int(pid), []), precedence) for pid in frame["player_id"]
    ]
    frame["value_eur"] = [None if v is None else v.value_eur for v in chosen]
    frame["value_date"] = [None if v is None else v.tm_last_updated for v in chosen]
    frame["value_source"] = [None if v is None else v.source for v in chosen]
    frame["value_is_stale"] = [None if v is None else v.is_stale for v in chosen]
    frame["age"] = [
        None if v is None else age_on(players.get(int(pid), (None, None))[1], v.tm_last_updated)
        for pid, v in zip(frame["player_id"], chosen, strict=True)
    ]
    keep = (
        frame["value_eur"].notna()
        & frame["position_group"].notna()
        & (frame["effective_minutes"] >= cfg.min_minutes)
    )
    logger.info(
        "value scoring frame",
        extra={"season": current, "rows": int(keep.sum()), "not_scored": int((~keep).sum())},
    )
    return frame[keep].reset_index(drop=True)
