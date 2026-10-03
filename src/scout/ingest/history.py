"""Past FPL seasons from the ``vaastav/Fantasy-Premier-League`` archive (PRD §7.1).

FPL's ``element-summary`` history empties after a season ends, so past seasons come from
this archive (CLAUDE.md "Known gotchas"). Per season it reads ``gws/merged_gw.csv``
(player-match rows), ``players_raw.csv`` (season ``id`` → stable ``code``) and
``teams.csv``. Columns added in later seasons (defensive fields from 2025-26, expected
stats from 2022-23) are optional: when absent they are ``None``, never 0 (CLAUDE.md rule 2).
"""

from __future__ import annotations

import io
import logging
import math
import re
from collections.abc import Sequence

import pandas as pd

from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "vaastav"
_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")

REQUIRED_GW = frozenset(
    {
        "element",
        "fixture",
        "opponent_team",
        "was_home",
        "kickoff_time",
        "round",
        "minutes",
        "goals_scored",
        "assists",
        "yellow_cards",
        "red_cards",
    }
)
# vaastav column → fact_player_match column; missing columns become None.
OPTIONAL_GW = {
    "starts": "starts",
    "expected_goals": "xg",
    "expected_assists": "xa",
    "expected_goals_conceded": "xgc_on_pitch",
    "tackles": "tackles",
    "clearances_blocks_interceptions": "cbi",
    "recoveries": "recoveries",
    "defensive_contribution": "def_contribution",
}
REQUIRED_PLAYERS = frozenset({"id", "code"})
REQUIRED_TEAMS = frozenset({"id", "code", "name"})


def previous_seasons(current: str, n: int) -> list[str]:
    """Return the ``n`` seasons before ``current`` (most recent first).

    ``current`` comes from FPL ``bootstrap-static`` (CLAUDE.md rule 7), e.g. ``"2026-27"``
    gives ``["2025-26", "2024-25", ...]``.
    """
    match = _SEASON_RE.match(current)
    if match is None:
        raise ValueError(f"season must look like 'YYYY-YY', got {current!r}")
    start = int(match.group(1))
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start - 1, start - 1 - n, -1)]


def snapshot_names(season: str) -> tuple[str, str, str]:
    """Snapshot file names for one season: (merged_gw, players_raw, teams)."""
    return (f"{season}_merged_gw.csv", f"{season}_players_raw.csv", f"{season}_teams.csv")


def _read_csv(snapshot: RawSnapshot, required: frozenset[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.BytesIO(snapshot.read_bytes()))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise DataValidationError(f"vaastav {snapshot.name} is not a valid CSV") from exc
    missing = required - set(frame.columns)
    if missing:
        raise DataValidationError(
            f"vaastav schema changed in {snapshot.name}: missing {sorted(missing)}"
        )
    return frame


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise DataValidationError(f"vaastav was_home value {value!r} is not boolean")


def _optional(value: object) -> object:
    """Map pandas' NaN for an empty CSV cell (or an absent column) to ``None``."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


class VaastavHistoryAdapter(SourceAdapter):
    """Fetch and parse past seasons from the vaastav archive."""

    source = SOURCE

    def __init__(self, base_url: str, seasons: Sequence[str]) -> None:
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        for season in seasons:
            if _SEASON_RE.match(season) is None:
                raise ValueError(f"season must look like 'YYYY-YY', got {season!r}")
        self.seasons = list(seasons)

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot the three CSVs for each configured season."""
        snapshots: list[RawSnapshot] = []
        for season in self.seasons:
            gw_name, players_name, teams_name = snapshot_names(season)
            root = f"{self.base_url}{season}/"
            for url, name in (
                (root + "gws/merged_gw.csv", gw_name),
                (root + "players_raw.csv", players_name),
                (root + "teams.csv", teams_name),
            ):
                snapshots.append(store.write(SOURCE, name, client.get(url)))
        return snapshots

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Player-match rows for every season present, keyed on FPL ``code``."""
        by_name = {s.name: s for s in snapshots}
        frames: list[pd.DataFrame] = []
        for season in self.seasons:
            names = snapshot_names(season)
            missing = [n for n in names if n not in by_name]
            if missing:
                raise DataValidationError(f"vaastav snapshots missing for {season}: {missing}")
            frames.append(self._parse_season(season, *(by_name[n] for n in names)))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _parse_season(
        self, season: str, gw: RawSnapshot, players: RawSnapshot, teams: RawSnapshot
    ) -> pd.DataFrame:
        gw_df = _read_csv(gw, REQUIRED_GW)
        players_df = _read_csv(players, REQUIRED_PLAYERS)
        teams_df = _read_csv(teams, REQUIRED_TEAMS)
        player_codes = dict(zip(players_df["id"], players_df["code"], strict=True))
        player_team: dict[int, int] = (
            dict(zip(players_df["id"], players_df["team"], strict=True))
            if "team" in players_df.columns
            else {}
        )
        team_codes = dict(zip(teams_df["id"], teams_df["code"], strict=True))

        rows: list[dict[str, object]] = []
        for rec in gw_df.to_dict(orient="records"):
            element = int(rec["element"])
            opponent = int(rec["opponent_team"])
            if element not in player_codes:
                raise DataValidationError(f"vaastav {season}: element {element} not in players")
            if opponent not in team_codes:
                raise DataValidationError(f"vaastav {season}: team {opponent} not in teams")
            team_id = player_team.get(element)
            starts = _optional(rec.get("starts"))
            row: dict[str, object] = {
                "fpl_code": int(player_codes[element]),
                "season_id": season,
                "fpl_fixture_id": int(rec["fixture"]),
                "gameweek": int(rec["round"]),
                "kickoff": pd.Timestamp(rec["kickoff_time"]),
                # players_raw holds the end-of-season club; mid-season movers are resolved
                # against fixtures in the warehouse build (M2).
                "team_fpl_code_end_of_season": (
                    int(team_codes[int(team_id)]) if team_id in team_codes else None
                ),
                "opponent_fpl_code": int(team_codes[opponent]),
                "was_home": _as_bool(rec["was_home"]),
                "minutes": int(rec["minutes"]),
                "started": None if starts is None else bool(int(str(starts)) > 0),
                "goals": int(rec["goals_scored"]),
                "assists": int(rec["assists"]),
                "yellow_cards": int(rec["yellow_cards"]),
                "red_cards": int(rec["red_cards"]),
                "source": SOURCE,
                "fetched_at": gw.fetched_at,
            }
            for column, target in OPTIONAL_GW.items():
                if target == "starts":
                    continue
                value = _optional(rec.get(column))
                row[target] = None if value is None else float(str(value))
            rows.append(row)
        logger.info("vaastav season parsed", extra={"season": season, "rows": len(rows)})
        return pd.DataFrame(rows)
