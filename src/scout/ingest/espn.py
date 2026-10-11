"""ESPN adapter for team possession per match (PRD §7.1 Tier 1b, §8.4; ADR-0002).

Possession is only needed to possession-adjust defensive volume stats (PRD §8.4). FotMob
was the planned source, but ``soccerdata`` 1.9 removed its FotMob reader at FotMob's
request, so it is not scraped (CLAUDE.md rule 11). ESPN's public scoreboard JSON lists each
team's ``possessionPct`` for finished Premier League matches.

Fetch: one request returns the season's calendar of match days (any date inside the season
does), then one request per match day up to today. Each season is stored as one JSON
snapshot of the raw day responses, so builds replay offline.

Parse: one row per team per completed match, with the team's and the opponent's possession
share in [0, 1]. A missing ``possessionPct`` stays missing and that match stays unadjusted
(CLAUDE.md rule 2); shares must sum to 1 within the configured tolerance. Matching to FPL
fixtures happens in the warehouse build on season + clubs.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "espn"
POSSESSION = "possessionPct"
# 1 August falls inside every Premier League season (ESPN seasons run 1 June to 31 May),
# so a scoreboard request for that day returns the whole season's calendar.
CALENDAR_PROBE = "0801"
_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")


def snapshot_name(season: str) -> str:
    """Snapshot file name for one season."""
    return f"{season}_scoreboards.json"


def parse_possession(value: object) -> float | None:
    """Parse ESPN possession (``"43.4"``, ``43.4`` or ``"43.4%"``) into a share.

    Returns:
        A fraction in [0, 1], or ``None`` if missing.

    Raises:
        DataValidationError: If the value is not a percentage.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().rstrip("%").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise DataValidationError(f"espn possession {value!r} is not a number") from exc
    if not 0.0 <= number <= 100.0:
        raise DataValidationError(f"espn possession {value!r} is out of range")
    return number / 100.0


def _start_year(season: str) -> int:
    match = _SEASON_RE.match(season)
    if match is None:
        raise ValueError(f"season must look like 'YYYY-YY', got {season!r}")
    return int(match.group(1))


def _schema_error(snap: RawSnapshot, what: str) -> DataValidationError:
    return DataValidationError(f"espn schema changed in {snap.name}: {what}")


class EspnAdapter(SourceAdapter):
    """Fetch and parse ESPN team possession for the Premier League."""

    source = SOURCE

    def __init__(
        self,
        base_url: str,
        seasons: Sequence[str],
        possession_sum_tolerance: float,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        for season in seasons:
            _start_year(season)
        self.seasons = list(seasons)
        self.tolerance = possession_sum_tolerance
        self._today = today or (lambda: datetime.now(UTC).date())

    def _scoreboard(self, client: PoliteClient, day: str) -> dict[str, Any]:
        body = client.get(self.base_url + "scoreboard", params={"dates": day})
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DataValidationError(f"espn scoreboard for {day} is not JSON") from exc
        if not isinstance(payload, dict):
            raise DataValidationError(f"espn scoreboard for {day} is not an object")
        return payload

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot every match day's scoreboard so far, one JSON file per season."""
        snapshots: list[RawSnapshot] = []
        today = self._today()
        for season in self.seasons:
            year = _start_year(season)
            probe = self._scoreboard(client, f"{year}{CALENDAR_PROBE}")
            try:
                league = probe["leagues"][0]
                calendar = [str(d) for d in league["calendar"]]
                season_year = int(league["season"]["year"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise DataValidationError("espn schema changed: no season calendar") from exc
            if season_year != year:
                raise DataValidationError(
                    f"espn returned season {season_year} when asked for {season}"
                )
            days: dict[str, Any] = {}
            for entry in calendar:
                day = pd.Timestamp(entry).date()
                if day > today:
                    continue
                key = day.strftime("%Y%m%d")
                days[key] = self._scoreboard(client, key)
            payload = {"season": season, "calendar": calendar, "days": days}
            snapshots.append(
                store.write(SOURCE, snapshot_name(season), json.dumps(payload).encode())
            )
        return snapshots

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Team-match possession rows for every configured season."""
        by_name = {s.name: s for s in snapshots}
        frames = []
        for season in self.seasons:
            snap = by_name.get(snapshot_name(season))
            if snap is None:
                raise DataValidationError(f"espn snapshot for {season} missing from this run")
            frames.append(self._parse_season(season, snap))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _parse_season(self, season: str, snap: RawSnapshot) -> pd.DataFrame:
        payload = snap.read_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("days"), dict):
            raise _schema_error(snap, "no 'days' object")
        rows: list[dict[str, object]] = []
        seen: set[int] = set()
        for day, response in sorted(payload["days"].items()):
            events = response.get("events") if isinstance(response, dict) else None
            if not isinstance(events, list):
                raise _schema_error(snap, f"day {day} has no 'events' list")
            for event in events:
                parsed = self._parse_event(snap, event)
                if parsed is None:
                    continue
                event_id, kickoff, sides = parsed
                if event_id in seen:
                    continue
                seen.add(event_id)
                rows.extend(self._rows(season, snap, event_id, kickoff, sides))
        logger.info("espn possession parsed", extra={"season": season, "rows": len(rows)})
        columns = [
            "season_id",
            "espn_event_id",
            "date",
            "kickoff",
            "team_name",
            "opponent_name",
            "is_home",
            "possession_share",
            "opp_possession_share",
            "source",
            "fetched_at",
        ]
        return pd.DataFrame(rows, columns=columns)

    def _parse_event(
        self, snap: RawSnapshot, event: object
    ) -> tuple[int, pd.Timestamp, dict[str, tuple[str, float | None]]] | None:
        """``(event id, kickoff, side → (team, share))``; ``None`` if not finished."""
        if not isinstance(event, Mapping):
            raise _schema_error(snap, "an event is not an object")
        try:
            event_id = int(event["id"])
            kickoff = pd.Timestamp(event["date"])
            competition = event["competitions"][0]
            status = event.get("status") or competition["status"]
            completed = bool(status["type"]["completed"])
            competitors = competition["competitors"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _schema_error(snap, "event without id, date, status or competitors") from exc
        if not completed:
            return None
        sides: dict[str, tuple[str, float | None]] = {}
        for competitor in competitors:
            try:
                side = str(competitor["homeAway"])
                team = str(competitor["team"]["displayName"])
            except (KeyError, TypeError) as exc:
                raise _schema_error(snap, f"event {event_id} competitor without team") from exc
            stats = competitor.get("statistics") or []
            value = next(
                (s.get("displayValue") for s in stats if s.get("name") == POSSESSION), None
            )
            sides[side] = (team, parse_possession(value))
        if set(sides) != {"home", "away"}:
            raise _schema_error(snap, f"event {event_id} does not have one home and one away")
        home, away = sides["home"][1], sides["away"][1]
        if home is not None and away is not None and abs(home + away - 1.0) > self.tolerance:
            raise DataValidationError(f"espn event {event_id} possession sums to {home + away:.3f}")
        if kickoff.tzinfo is None:
            kickoff = kickoff.tz_localize(UTC)
        return event_id, kickoff, sides

    @staticmethod
    def _rows(
        season: str,
        snap: RawSnapshot,
        event_id: int,
        kickoff: pd.Timestamp,
        sides: Mapping[str, tuple[str, float | None]],
    ) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for side, other in (("home", "away"), ("away", "home")):
            team, share = sides[side]
            opponent, opp_share = sides[other]
            out.append(
                {
                    "season_id": season,
                    "espn_event_id": event_id,
                    "date": kickoff.date(),
                    "kickoff": kickoff,
                    "team_name": team,
                    "opponent_name": opponent,
                    "is_home": side == "home",
                    "possession_share": share,
                    "opp_possession_share": opp_share,
                    "source": SOURCE,
                    "fetched_at": snap.fetched_at,
                }
            )
        return out
