"""Load validated silver tables into the warehouse (gold layer, PRD §11).

Dimensions are get-or-create on natural keys, so re-running a build updates rows instead
of duplicating them. Matches from different sources are joined on
``(season, home club, away club)``: in a league season each home/away pairing happens
exactly once, which is more robust than kickoff dates that can differ by time zone.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from scout.config import PositionsConfig
from scout.db.models import (
    DimMatch,
    DimPlayer,
    DimSeason,
    DimTeam,
    EntityMapReview,
    FactMarketValue,
    FactPlayerMatch,
    FactPlayerStatus,
    FactTeamMatch,
    PlayerSeasonFeature,
    SourceSnapshot,
)
from scout.ingest.base import RawSnapshot
from scout.transform.entity_resolution import ReviewItem

logger = logging.getLogger(__name__)


def _opt_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(str(value))


def _opt_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


class DimensionLoader:
    """Get-or-create loaders for seasons, teams, players and matches."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- seasons -----------------------------------------------------------------------

    def season(self, season_id: str, *, is_current: bool) -> DimSeason:
        """Ensure a season row exists; only one season is marked current."""
        row = self.session.get(DimSeason, season_id)
        if row is None:
            row = DimSeason(season_id=season_id, is_current=is_current)
            self.session.add(row)
        if is_current:
            for other in self.session.scalars(select(DimSeason).where(DimSeason.is_current)):
                if other.season_id != season_id:
                    other.is_current = False
            row.is_current = True
        self.session.flush()
        return row

    # -- teams -------------------------------------------------------------------------

    def teams_from_fpl(
        self, teams: pd.DataFrame, aliases: Mapping[str, list[str]]
    ) -> dict[int, int]:
        """Upsert FPL clubs; returns ``fpl_code → team_id``."""
        out: dict[int, int] = {}
        for rec in teams.to_dict(orient="records"):
            code = int(rec["fpl_code"])
            row = self.session.scalars(select(DimTeam).where(DimTeam.fpl_code == code)).first()
            if row is None:
                row = DimTeam(fpl_code=code, name=str(rec["name"]))
                self.session.add(row)
            row.name = str(rec["name"])
            row.short_name = _opt_str(rec.get("short_name"))
            row.aliases = json.dumps(aliases.get(row.name, []))
            self.session.flush()
            out[code] = row.team_id
        return out

    def team_for_source(
        self,
        name: str,
        *,
        fpl_code: int | None = None,
        understat_id: int | None = None,
        tm_id: str | None = None,
    ) -> int:
        """Find a club by any source id (or FPL code), attach the new ids, or create it."""
        row: DimTeam | None = None
        if understat_id is not None:
            row = self.session.scalars(
                select(DimTeam).where(DimTeam.understat_id == understat_id)
            ).first()
        if row is None and tm_id is not None:
            row = self.session.scalars(select(DimTeam).where(DimTeam.tm_id == tm_id)).first()
        if row is None and fpl_code is not None:
            row = self.session.scalars(select(DimTeam).where(DimTeam.fpl_code == fpl_code)).first()
        if row is None:
            # A club outside the current FPL season (e.g. relegated last season). Its FPL
            # team code is stable across seasons, so keep it when known.
            row = DimTeam(name=name, fpl_code=fpl_code)
            self.session.add(row)
        if understat_id is not None:
            row.understat_id = understat_id
        if tm_id is not None:
            row.tm_id = tm_id
        self.session.flush()
        return row.team_id

    # -- players -----------------------------------------------------------------------

    def players(
        self,
        mapping: pd.DataFrame,
        fpl_players: pd.DataFrame,
        tm_values: pd.DataFrame | None,
        positions: PositionsConfig,
    ) -> dict[int, int]:
        """Upsert resolved players; returns ``fpl_code → player_id``.

        Position group comes from Transfermarkt's detailed position (PRD §8.5), falling
        back to the coarse FPL position; goalkeepers get no group (GK is stretch S2).
        """
        fpl_pos = {
            int(r["fpl_code"]): str(r["fpl_position"])
            for r in fpl_players.to_dict(orient="records")
        }
        tm_by_id: dict[str, dict[Hashable, Any]] = {}
        if tm_values is not None:
            tm_by_id = {str(r["tm_player_id"]): r for r in tm_values.to_dict(orient="records")}
        out: dict[int, int] = {}
        for rec in mapping.to_dict(orient="records"):
            code = int(rec["fpl_code"])
            tm_id = _opt_str(rec.get("transfermarkt_id"))
            tm = tm_by_id.get(tm_id, {}) if tm_id else {}
            detailed = _opt_str(tm.get("tm_position"))
            group = positions.transfermarkt.get(detailed) if detailed else None
            if group is None:
                coarse = fpl_pos.get(code)
                group = next(
                    (g for k, g in positions.fpl_element_type_fallback.items() if k == coarse),
                    None,
                )
            row = self.session.scalars(select(DimPlayer).where(DimPlayer.fpl_code == code)).first()
            if row is None:
                row = DimPlayer(fpl_code=code, canonical_name=str(rec["canonical_name"]))
                self.session.add(row)
            row.canonical_name = str(rec["canonical_name"])
            row.understat_id = _opt_int(rec.get("understat_id"))
            row.tm_id = tm_id
            birth = tm.get("birth_date")
            if isinstance(birth, date):
                row.birth_date = birth
            row.detailed_position = detailed
            row.position_group = group
            self.session.flush()
            out[code] = row.player_id
        return out

    # -- matches -----------------------------------------------------------------------

    def _match(self, season_id: str, home_id: int, away_id: int) -> DimMatch | None:
        return self.session.scalars(
            select(DimMatch).where(
                DimMatch.season_id == season_id,
                DimMatch.home_team_id == home_id,
                DimMatch.away_team_id == away_id,
            )
        ).first()

    def matches_from_fpl(
        self, fixtures: pd.DataFrame, team_ids: Mapping[int, int]
    ) -> dict[int, int]:
        """Upsert FPL fixtures; returns ``fpl_fixture_code → match_id``."""
        out: dict[int, int] = {}
        for rec in fixtures.to_dict(orient="records"):
            season_id = str(rec["season_id"])
            if self.session.get(DimSeason, season_id) is None:
                self.season(season_id, is_current=False)
            home = team_ids[int(rec["home_team_fpl_code"])]
            away = team_ids[int(rec["away_team_fpl_code"])]
            code = int(rec["fpl_fixture_code"])
            row = self.session.scalars(
                select(DimMatch).where(DimMatch.fpl_fixture_code == code)
            ).first()
            if row is None:
                # Adopt a match created from another source, but never one that already
                # belongs to a different FPL fixture.
                candidate = self._match(season_id, home, away)
                if candidate is not None and candidate.fpl_fixture_code is None:
                    row = candidate
            if row is None:
                row = DimMatch(season_id=season_id, home_team_id=home, away_team_id=away)
                self.session.add(row)
            row.fpl_fixture_code = code
            row.gameweek = _opt_int(rec.get("gameweek"))
            kickoff = rec.get("kickoff")
            row.kickoff = kickoff if isinstance(kickoff, datetime) and pd.notna(kickoff) else None
            row.home_score = _opt_int(rec.get("home_score"))
            row.away_score = _opt_int(rec.get("away_score"))
            self.session.flush()
            out[code] = row.match_id
        return out

    def matches_from_understat(
        self, team_match: pd.DataFrame, club_codes: Mapping[str, int | None]
    ) -> dict[int, int]:
        """Attach Understat game ids to matches (creating past-season matches).

        Returns ``understat_game_id → match_id``. ``team_match`` is the Understat
        team-match table (two rows per game).
        """
        out: dict[int, int] = {}
        homes = team_match[team_match["is_home"].astype(bool)]
        for rec in homes.to_dict(orient="records"):
            season_id = str(rec["season_id"])
            if self.session.get(DimSeason, season_id) is None:
                self.season(season_id, is_current=False)
            home = self.team_for_source(
                str(rec["team_name"]),
                fpl_code=club_codes.get(str(rec["team_name"])),
                understat_id=int(rec["understat_team_id"]),
            )
            away = self.team_for_source(
                str(rec["opponent_name"]),
                fpl_code=club_codes.get(str(rec["opponent_name"])),
                understat_id=int(rec["understat_opponent_id"]),
            )
            game_id = int(rec["understat_game_id"])
            row = self.session.scalars(
                select(DimMatch).where(DimMatch.understat_game_id == game_id)
            ).first() or self._match(season_id, home, away)
            if row is None:
                row = DimMatch(season_id=season_id, home_team_id=home, away_team_id=away)
                kickoff = rec.get("date")
                if isinstance(kickoff, datetime) and not pd.isna(kickoff):
                    row.kickoff = kickoff
                self.session.add(row)
            # Fill scores the match doesn't have yet (e.g. created from vaastav rows),
            # so last season's table counts every played match.
            if row.home_score is None and row.away_score is None:
                row.home_score = _opt_int(rec.get("goals"))
                row.away_score = _opt_int(rec.get("goals_against"))
            row.understat_game_id = game_id
            self.session.flush()
            out[game_id] = row.match_id
        return out

    def matches_from_vaastav(self, frame: pd.DataFrame) -> dict[tuple[str, int], int]:
        """Attach past-season FPL fixtures to matches; returns ``(season, fixture) → match``.

        vaastav rows give each player's opponent and ``was_home``. A fixture's home club
        is the opponent of its away players and vice versa, which avoids relying on the
        end-of-season club in ``players_raw`` (wrong for mid-season movers).
        """
        sides: dict[tuple[str, int], dict[str, tuple[int, str]]] = {}
        for rec in frame.to_dict(orient="records"):
            key = (str(rec["season_id"]), int(rec["fpl_fixture_id"]))
            side = "away" if bool(rec["was_home"]) else "home"  # the opponent's side
            sides.setdefault(key, {})[side] = (
                int(rec["opponent_fpl_code"]),
                str(rec["opponent_name"]),
            )
        out: dict[tuple[str, int], int] = {}
        for (season_id, fixture_id), teams in sides.items():
            if "home" not in teams or "away" not in teams:
                logger.warning(
                    "vaastav fixture has players from one side only",
                    extra={"season": season_id, "fixture": fixture_id},
                )
                continue
            if self.session.get(DimSeason, season_id) is None:
                self.season(season_id, is_current=False)
            home_code, home_name = teams["home"]
            away_code, away_name = teams["away"]
            home = self.team_for_source(home_name, fpl_code=home_code)
            away = self.team_for_source(away_name, fpl_code=away_code)
            row = self._match(season_id, home, away)
            if row is None:
                row = DimMatch(season_id=season_id, home_team_id=home, away_team_id=away)
                self.session.add(row)
                self.session.flush()
            out[(season_id, fixture_id)] = row.match_id
        return out

    def matches_from_fotmob(
        self, possession: pd.DataFrame, team_lookup: Mapping[str, int]
    ) -> dict[str, int]:
        """Attach FotMob game keys to existing matches; returns ``game → match_id``.

        FotMob game keys look like ``"2025-08-16 Home-Away"``; the home side is the team
        whose ``"{team}-{opponent}"`` ends the key. Games that match no known fixture
        are skipped (logged), never invented.
        """
        out: dict[str, int] = {}
        for rec in possession.to_dict(orient="records"):
            game, team, opp = str(rec["game"]), str(rec["team_name"]), str(rec["opponent_name"])
            if not game.endswith(f" {team}-{opp}") or game in out:
                continue
            home, away = team_lookup.get(team), team_lookup.get(opp)
            row = (
                self._match(str(rec["season_id"]), home, away)
                if home is not None and away is not None
                else None
            )
            if row is None:
                logger.warning("fotmob game not matched to a fixture", extra={"game": game})
                continue
            row.fotmob_game = game
            self.session.flush()
            out[game] = row.match_id
        return out


def _clean(value: object) -> object:
    """Convert pandas/numpy scalars to plain Python; NaN/NaT become None (never 0)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__ == "numpy":
        return _clean(item())
    return value


@dataclass
class FactLoadStats:
    """Rows written and source rows skipped (unresolved player/match) per fact table."""

    written: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


SourcedFact = FactPlayerMatch | FactTeamMatch | FactMarketValue | FactPlayerStatus


class FactLoader:
    """Replace each source's fact rows on every build (idempotent delete-and-insert)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.stats = FactLoadStats()

    def _replace(
        self, model: type[SourcedFact], source: str, rows: list[dict[str, object]]
    ) -> None:
        self.session.execute(delete(model).where(model.source == source))
        if rows:
            cleaned = [{k: _clean(v) for k, v in r.items()} for r in rows]
            self.session.execute(insert(model), cleaned)
        label = f"{model.__tablename__}:{source}"
        self.stats.written[label] = len(rows)

    def _skip(self, label: str) -> None:
        self.stats.skipped[label] = self.stats.skipped.get(label, 0) + 1

    def player_match_fpl(
        self,
        frame: pd.DataFrame,
        player_ids: Mapping[int, int],
        match_ids: Mapping[int, int],
        team_ids: Mapping[int, int],
    ) -> None:
        """FPL player-match rows keyed by FPL code / fixture code / team code."""
        rows: list[dict[str, object]] = []
        for rec in frame.to_dict(orient="records"):
            player = player_ids.get(int(rec["fpl_code"]))
            match = match_ids.get(int(rec["fpl_fixture_code"]))
            team = team_ids.get(int(rec["team_fpl_code"]))
            if player is None or match is None or team is None:
                self._skip("fact_player_match:fpl")
                continue
            rows.append(
                {
                    "player_id": player,
                    "match_id": match,
                    "team_id": team,
                    **{c: rec.get(c) for c in _FPL_PM_COLS},
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactPlayerMatch, "fpl", rows)

    def player_match_understat(
        self,
        frame: pd.DataFrame,
        player_ids: Mapping[int, int],
        match_ids: Mapping[int, int],
        team_ids: Mapping[int, int],
    ) -> None:
        """Understat rows keyed by Understat player / game / team ids."""
        rows: list[dict[str, object]] = []
        for rec in frame.to_dict(orient="records"):
            player = player_ids.get(int(rec["understat_player_id"]))
            match = match_ids.get(int(rec["understat_game_id"]))
            team = team_ids.get(int(rec["understat_team_id"]))
            if player is None or match is None or team is None:
                self._skip("fact_player_match:understat")
                continue
            rows.append(
                {
                    "player_id": player,
                    "match_id": match,
                    "team_id": team,
                    **{c: rec.get(c) for c in _UNDERSTAT_PM_COLS},
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactPlayerMatch, "understat", rows)

    def player_match_vaastav(
        self,
        frame: pd.DataFrame,
        player_ids: Mapping[int, int],
        match_ids: Mapping[tuple[str, int], int],
        team_ids: Mapping[int, int],
    ) -> None:
        """Past-season FPL rows from the vaastav archive (source ``vaastav``).

        The player's club for the match is the side opposite their opponent.
        """
        match_teams = self._match_teams(set(match_ids.values()))
        rows: list[dict[str, object]] = []
        for rec in frame.to_dict(orient="records"):
            player = player_ids.get(int(rec["fpl_code"]))
            match = match_ids.get((str(rec["season_id"]), int(rec["fpl_fixture_id"])))
            opponent = team_ids.get(int(rec["opponent_fpl_code"]))
            if player is None or match is None or opponent is None:
                self._skip("fact_player_match:vaastav")
                continue
            home, away = match_teams[match]
            rows.append(
                {
                    "player_id": player,
                    "match_id": match,
                    "team_id": away if opponent == home else home,
                    **{c: rec.get(c) for c in _FPL_PM_COLS},
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactPlayerMatch, "vaastav", rows)

    def _match_teams(self, match_ids: set[int]) -> dict[int, tuple[int, int]]:
        if not match_ids:
            return {}
        rows = self.session.execute(
            select(DimMatch.match_id, DimMatch.home_team_id, DimMatch.away_team_id).where(
                DimMatch.match_id.in_(match_ids)
            )
        ).all()
        return {m: (h, a) for m, h, a in rows}

    def team_match_understat(
        self, frame: pd.DataFrame, match_ids: Mapping[int, int], team_ids: Mapping[int, int]
    ) -> None:
        """Understat team-match rows (xG, PPDA, deep, set pieces)."""
        rows: list[dict[str, object]] = []
        for rec in frame.to_dict(orient="records"):
            match = match_ids.get(int(rec["understat_game_id"]))
            team = team_ids.get(int(rec["understat_team_id"]))
            if match is None or team is None:
                self._skip("fact_team_match:understat")
                continue
            rows.append(
                {
                    "match_id": match,
                    "team_id": team,
                    **{c: rec.get(c) for c in _UNDERSTAT_TM_COLS},
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactTeamMatch, "understat", rows)

    def team_possession_fotmob(
        self, frame: pd.DataFrame, match_ids: Mapping[str, int], team_ids: Mapping[str, int]
    ) -> None:
        """FotMob possession rows (share in [0, 1]; missing stays null)."""
        rows: list[dict[str, object]] = []
        for rec in frame.to_dict(orient="records"):
            match = match_ids.get(str(rec["game"]))
            team = team_ids.get(str(rec["team_name"]))
            if match is None or team is None:
                self._skip("fact_team_match:fotmob")
                continue
            rows.append(
                {
                    "match_id": match,
                    "team_id": team,
                    "possession": rec.get("possession_share"),
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactTeamMatch, "fotmob", rows)

    def market_values(self, frame: pd.DataFrame, player_ids: Mapping[str, int]) -> None:
        """Market values from one source (live, datasets snapshot or override)."""
        by_source: dict[str, list[dict[str, object]]] = {}
        for rec in frame.to_dict(orient="records"):
            source = str(rec["source"])
            by_source.setdefault(source, [])
            player = player_ids.get(str(rec["tm_player_id"]))
            if player is None:
                self._skip(f"fact_market_value:{source}")
                continue
            by_source[source].append(
                {
                    "player_id": player,
                    "value_eur": rec.get("value_eur"),
                    "tm_last_updated": rec.get("tm_last_updated"),
                    "is_stale": bool(rec.get("is_stale", False)),
                    "reason": rec.get("reason"),
                    "source": source,
                    "fetched_at": rec["fetched_at"],
                }
            )
        for source, rows in by_source.items():
            self._replace(FactMarketValue, source, rows)

    def player_status(
        self,
        fpl_players: pd.DataFrame,
        player_ids: Mapping[int, int],
        contracts: Mapping[int, date | None] | None = None,
    ) -> None:
        """FPL availability snapshot plus Transfermarkt contract expiry when known."""
        rows: list[dict[str, object]] = []
        for rec in fpl_players.to_dict(orient="records"):
            code = int(rec["fpl_code"])
            player = player_ids.get(code)
            if player is None:
                self._skip("fact_player_status:fpl")
                continue
            rows.append(
                {
                    "player_id": player,
                    "fpl_status": rec.get("fpl_status"),
                    "news": rec.get("news"),
                    "chance_of_playing": rec.get("chance_of_playing"),
                    "contract_expiry": (contracts or {}).get(code),
                    "source": rec["source"],
                    "fetched_at": rec["fetched_at"],
                }
            )
        self._replace(FactPlayerStatus, "fpl", rows)

    def snapshots(self, snapshots: Sequence[RawSnapshot], status: str, rows: int | None) -> None:
        """Record ingested raw snapshots for freshness reporting (``scout doctor``)."""
        for snap in snapshots:
            self.session.add(
                SourceSnapshot(
                    source=snap.source,
                    name=snap.name,
                    fetched_at=snap.fetched_at,
                    rows=rows,
                    checksum=snap.checksum,
                    status=status,
                )
            )
        self.session.flush()

    def review(
        self, items: Sequence[ReviewItem], player_ids: Mapping[int, int], now: datetime
    ) -> None:
        """Replace the entity review queue with this build's unresolved records."""
        self.session.execute(delete(EntityMapReview))
        for item in items:
            self.session.add(
                EntityMapReview(
                    source=item.source,
                    source_id=item.source_id,
                    name=item.name,
                    team=item.team,
                    best_candidate=(
                        player_ids.get(item.best_candidate)
                        if item.best_candidate is not None
                        else None
                    ),
                    score=item.score,
                    created_at=now,
                )
            )
        self.session.flush()


_FPL_PM_COLS = (
    "minutes",
    "started",
    "goals",
    "assists",
    "xg",
    "xa",
    "xgc_on_pitch",
    "tackles",
    "cbi",
    "recoveries",
    "def_contribution",
    "yellow_cards",
    "red_cards",
)
_UNDERSTAT_PM_COLS = (
    "minutes",
    "goals",
    "shots",
    "xg",
    "npxg",
    "xa",
    "xg_chain",
    "xg_buildup",
    "key_passes",
    "assists",
    "yellow_cards",
    "red_cards",
)
_UNDERSTAT_TM_COLS = (
    "xg",
    "xga",
    "npxg",
    "npxga",
    "ppda",
    "ppda_allowed",
    "deep",
    "deep_allowed",
    "set_piece_xg",
    "set_piece_xga",
    "open_play_xga",
)


def replace_player_season_features(session: Session, frame: pd.DataFrame) -> int:
    """Replace the materialised feature table; returns rows written."""
    session.execute(delete(PlayerSeasonFeature))
    columns = [c.name for c in PlayerSeasonFeature.__table__.columns if c.name != "id"]
    rows = [{c: _clean(rec.get(c)) for c in columns} for rec in frame.to_dict(orient="records")]
    if rows:
        session.execute(insert(PlayerSeasonFeature), rows)
    return len(rows)
