"""Understat adapter (PRD §7.1, Tier 1) backed by a pinned ``soccerdata``.

Understat supplies player-match xG, xA, shots, key passes, xGChain and xGBuildup, shot
events with their situation, and team-match PPDA and deep completions. ``soccerdata``
does the scraping; its DataFrames are written to the bronze store as CSV so builds can be
replayed offline, then parsed here with explicit column contracts so a schema change fails
loudly (CLAUDE.md "Contract tests per adapter").

Derived values:
- **npxG** per player-match = xG minus the xG of that player's penalty shots in the match
  (PRD §8.7 uses npxG so penalty takers aren't over-rated).
- **Set-piece xG / xGA** per team-match = xG of shots whose situation is a set piece
  (corner, set piece, direct free kick); **open-play xGA** = opponent open-play shot xG.
- **PPDA allowed** = the opponent's PPDA in the same match (press resistance).
"""

from __future__ import annotations

import io
import logging
import math
import re
from collections.abc import Callable, Sequence

import pandas as pd

from scout.errors import DataValidationError, SourceUnavailableError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "understat"
LEAGUE = "ENG-Premier League"
_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")

PENALTY = "Penalty"
SET_PIECE_SITUATIONS = frozenset({"From Corner", "Set Piece", "Direct Freekick"})
OPEN_PLAY = "Open Play"

REQUIRED_PLAYER = frozenset(
    {
        "game_id",
        "team_id",
        "team",
        "player_id",
        "player",
        "minutes",
        "goals",
        "shots",
        "xg",
        "xa",
        "xg_chain",
        "xg_buildup",
        "key_passes",
    }
)
OPTIONAL_PLAYER = ("position", "assists", "yellow_cards", "red_cards")
REQUIRED_SHOTS = frozenset({"game_id", "player_id", "team", "xg", "situation"})
REQUIRED_TEAM = frozenset(
    {
        "game_id",
        "date",
        "home_team_id",
        "away_team_id",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "home_xg",
        "away_xg",
        "home_np_xg",
        "away_np_xg",
        "home_ppda",
        "away_ppda",
        "home_deep_completions",
        "away_deep_completions",
    }
)

# Snapshot kinds → soccerdata reader method names.
KINDS = {
    "player_match": "read_player_match_stats",
    "shots": "read_shot_events",
    "team_match": "read_team_match_stats",
}

ReaderFactory = Callable[[str], object]


def snapshot_name(season: str, kind: str) -> str:
    """Snapshot file name for one season and kind."""
    return f"{season}_{kind}.csv"


def soccerdata_season(season: str) -> str:
    """Convert ``"2025-26"`` to soccerdata's ``"2526"`` season code."""
    match = _SEASON_RE.match(season)
    if match is None:
        raise ValueError(f"season must look like 'YYYY-YY', got {season!r}")
    return f"{match.group(1)[2:]}{match.group(2)}"


def _default_reader(season: str) -> object:  # pragma: no cover - needs network + soccerdata
    try:
        import soccerdata
    except ImportError as exc:
        raise SourceUnavailableError(
            "soccerdata is not installed; run `uv sync --all-extras`"
        ) from exc
    return soccerdata.Understat(leagues=LEAGUE, seasons=soccerdata_season(season))


def _read_csv(snapshot: RawSnapshot, required: frozenset[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.BytesIO(snapshot.read_bytes()))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise DataValidationError(f"understat {snapshot.name} is not a valid CSV") from exc
    missing = required - set(frame.columns)
    if missing:
        raise DataValidationError(
            f"understat schema changed in {snapshot.name}: missing {sorted(missing)}"
        )
    return frame


def _opt_float(value: object) -> float | None:
    """Return a float, or ``None`` for a missing value (never 0; CLAUDE.md rule 2)."""
    if value is None:
        return None
    number = float(str(value))
    return None if math.isnan(number) else number


def _opt_int(value: object) -> int | None:
    number = _opt_float(value)
    return None if number is None else int(number)


class UnderstatAdapter(SourceAdapter):
    """Fetch and parse Understat data for the Premier League."""

    source = SOURCE

    def __init__(self, seasons: Sequence[str], reader_factory: ReaderFactory | None = None) -> None:
        for season in seasons:
            if _SEASON_RE.match(season) is None:
                raise ValueError(f"season must look like 'YYYY-YY', got {season!r}")
        self.seasons = list(seasons)
        self._reader_factory = reader_factory or _default_reader

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot player-match stats, shot events and team-match stats per season."""
        snapshots: list[RawSnapshot] = []
        for season in self.seasons:
            reader = self._reader_factory(season)
            for kind, method in KINDS.items():
                client.throttle()
                frame = getattr(reader, method)()
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    raise SourceUnavailableError(f"understat returned no {kind} data for {season}")
                payload = frame.reset_index().to_csv(index=False).encode()
                snapshots.append(store.write(SOURCE, snapshot_name(season, kind), payload))
        return snapshots

    def _snap(self, snapshots: Sequence[RawSnapshot], season: str, kind: str) -> RawSnapshot:
        name = snapshot_name(season, kind)
        for snap in snapshots:
            if snap.name == name:
                return snap
        raise DataValidationError(f"understat snapshot {name} missing from this run")

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Player-match rows with npxG derived from shot events."""
        frames = [self._parse_players(snapshots, season) for season in self.seasons]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def parse_team_match(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Team-match rows (two per game) with PPDA, deep and set-piece splits."""
        frames = [self._parse_teams(snapshots, season) for season in self.seasons]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _shots(self, snapshots: Sequence[RawSnapshot], season: str) -> pd.DataFrame:
        shots = _read_csv(self._snap(snapshots, season, "shots"), REQUIRED_SHOTS)
        shots["xg"] = pd.to_numeric(shots["xg"], errors="raise")
        return shots

    def _parse_players(self, snapshots: Sequence[RawSnapshot], season: str) -> pd.DataFrame:
        snap = self._snap(snapshots, season, "player_match")
        players = _read_csv(snap, REQUIRED_PLAYER)
        shots = self._shots(snapshots, season)
        pens = shots[shots["situation"] == PENALTY]
        pen_xg: dict[tuple[int, int], float] = {}
        for r in pens.to_dict(orient="records"):
            key = (int(r["game_id"]), int(r["player_id"]))
            pen_xg[key] = pen_xg.get(key, 0.0) + float(r["xg"])
        rows: list[dict[str, object]] = []
        for rec in players.to_dict(orient="records"):
            game_id, player_id = int(rec["game_id"]), int(rec["player_id"])
            xg = _opt_float(rec["xg"])
            row: dict[str, object] = {
                "understat_player_id": player_id,
                "understat_game_id": game_id,
                "understat_team_id": int(rec["team_id"]),
                "player_name": str(rec["player"]),
                "team_name": str(rec["team"]),
                "season_id": season,
                "minutes": int(rec["minutes"]),
                "goals": int(rec["goals"]),
                "shots": int(rec["shots"]),
                "xg": xg,
                "npxg": None
                if xg is None
                else max(0.0, xg - pen_xg.get((game_id, player_id), 0.0)),
                "xa": _opt_float(rec["xa"]),
                "xg_chain": _opt_float(rec["xg_chain"]),
                "xg_buildup": _opt_float(rec["xg_buildup"]),
                "key_passes": int(rec["key_passes"]),
                "source": SOURCE,
                "fetched_at": snap.fetched_at,
            }
            for column in OPTIONAL_PLAYER:
                value = rec.get(column)
                if column == "position":
                    row[column] = None if _is_missing(value) else str(value)
                else:
                    row[column] = _opt_int(value)
            rows.append(row)
        return pd.DataFrame(rows)

    def _parse_teams(self, snapshots: Sequence[RawSnapshot], season: str) -> pd.DataFrame:
        snap = self._snap(snapshots, season, "team_match")
        games = _read_csv(snap, REQUIRED_TEAM)
        shots = self._shots(snapshots, season)
        set_piece = _xg_by_game_team(shots[shots["situation"].isin(SET_PIECE_SITUATIONS)])
        open_play = _xg_by_game_team(shots[shots["situation"] == OPEN_PLAY])
        games_with_shots = {int(g) for g in shots["game_id"].unique()}
        rows: list[dict[str, object]] = []
        for rec in games.to_dict(orient="records"):
            game_id = int(rec["game_id"])
            has_shots = game_id in games_with_shots
            for side, other in (("home", "away"), ("away", "home")):
                team, opp = str(rec[f"{side}_team"]), str(rec[f"{other}_team"])

                rows.append(
                    {
                        "understat_game_id": game_id,
                        "understat_team_id": int(rec[f"{side}_team_id"]),
                        "understat_opponent_id": int(rec[f"{other}_team_id"]),
                        "team_name": team,
                        "opponent_name": opp,
                        "season_id": season,
                        "date": pd.Timestamp(rec["date"]),
                        "is_home": side == "home",
                        "goals": _opt_int(rec[f"{side}_goals"]),
                        "goals_against": _opt_int(rec[f"{other}_goals"]),
                        "xg": _opt_float(rec[f"{side}_xg"]),
                        "xga": _opt_float(rec[f"{other}_xg"]),
                        "npxg": _opt_float(rec[f"{side}_np_xg"]),
                        "npxga": _opt_float(rec[f"{other}_np_xg"]),
                        "ppda": _opt_float(rec[f"{side}_ppda"]),
                        "ppda_allowed": _opt_float(rec[f"{other}_ppda"]),
                        "deep": _opt_int(rec[f"{side}_deep_completions"]),
                        "deep_allowed": _opt_int(rec[f"{other}_deep_completions"]),
                        "set_piece_xg": _shot_sum(set_piece, game_id, team, has_shots),
                        "set_piece_xga": _shot_sum(set_piece, game_id, opp, has_shots),
                        "open_play_xga": _shot_sum(open_play, game_id, opp, has_shots),
                        "source": SOURCE,
                        "fetched_at": snap.fetched_at,
                    }
                )
        logger.info("understat team-match parsed", extra={"season": season, "rows": len(rows)})
        return pd.DataFrame(rows)


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _shot_sum(
    table: dict[tuple[int, str], float], game_id: int, team: str, has_shots: bool
) -> float | None:
    """Sum of shot xG for ``team`` in ``game_id``; ``None`` if the game has no shot events.

    A game with shot events where this team took none of the given kind is a real 0.0;
    a game with no shot events at all is unknown (CLAUDE.md rule 2).
    """
    return table.get((game_id, team), 0.0) if has_shots else None


def _xg_by_game_team(shots: pd.DataFrame) -> dict[tuple[int, str], float]:
    """Total shot xG keyed by ``(game_id, team)``."""
    totals: dict[tuple[int, str], float] = {}
    for r in shots.to_dict(orient="records"):
        key = (int(r["game_id"]), str(r["team"]))
        totals[key] = totals.get(key, 0.0) + float(r["xg"])
    return totals
