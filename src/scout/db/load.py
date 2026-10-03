"""Load validated silver tables into the warehouse (gold layer, PRD §11).

Dimensions are get-or-create on natural keys, so re-running a build updates rows instead
of duplicating them. Matches from different sources are joined on
``(season, home club, away club)``: in a league season each home/away pairing happens
exactly once, which is more robust than kickoff dates that can differ by time zone.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Hashable, Mapping
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.config import PositionsConfig
from scout.db.models import DimMatch, DimPlayer, DimSeason, DimTeam

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
            # A club outside the current FPL season (e.g. relegated last season).
            row = DimTeam(name=name)
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
            ).first() or self._match(season_id, home, away)
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
                row.home_score = _opt_int(rec.get("goals"))
                row.away_score = _opt_int(rec.get("goals_against"))
                self.session.add(row)
            row.understat_game_id = game_id
            self.session.flush()
            out[game_id] = row.match_id
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
