"""StatsBomb open-data loader (PRD §7.1; dev/validation only).

Historical event data used to develop and unit-test event-derived metric definitions
before the Tier-2 event adapter exists. It is never used for current-season KPIs. Reads
the public GitHub JSON directly (``matches/{competition}/{season}.json`` and
``events/{match_id}.json``), so no extra dependency is needed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pandas as pd

from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "statsbomb"


def matches_name(competition_id: int, season_id: int) -> str:
    """Snapshot name for a competition-season match list."""
    return f"matches-{competition_id}-{season_id}.json"


def events_name(match_id: int) -> str:
    """Snapshot name for one match's events."""
    return f"events-{match_id}.json"


def _xy(value: Any, what: str) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    if not isinstance(value, list) or len(value) < 2:
        raise DataValidationError(f"statsbomb {what} is not an [x, y] list")
    return float(value[0]), float(value[1])


def _name(obj: Any) -> str | None:
    value = obj.get("name") if isinstance(obj, dict) else None
    return None if value is None else str(value)


def _id(obj: Any) -> int | None:
    value = obj.get("id") if isinstance(obj, dict) else None
    return None if value is None else int(value)


class StatsBombAdapter(SourceAdapter):
    """Fetch and flatten StatsBomb open event data for one competition-season."""

    source = SOURCE

    def __init__(
        self, base_url: str, competition_id: int, season_id: int, max_matches: int
    ) -> None:
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.competition_id = competition_id
        self.season_id = season_id
        self.max_matches = max_matches

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot the match list and events for the first ``max_matches`` matches."""
        url = f"{self.base_url}matches/{self.competition_id}/{self.season_id}.json"
        name = matches_name(self.competition_id, self.season_id)
        matches_snap = store.write(SOURCE, name, client.get(url))
        snapshots = [matches_snap]
        for match in self._matches(matches_snap)[: self.max_matches]:
            match_id = int(match["match_id"])
            body = client.get(f"{self.base_url}events/{match_id}.json")
            snapshots.append(store.write(SOURCE, events_name(match_id), body))
        return snapshots

    @staticmethod
    def _matches(snapshot: RawSnapshot) -> list[dict[str, Any]]:
        payload = snapshot.read_json()
        if not isinstance(payload, list) or not all(
            isinstance(m, dict) and "match_id" in m for m in payload
        ):
            raise DataValidationError("statsbomb schema changed in matches: expected match list")
        return payload

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """One row per event with type, team, player, locations and shot xG."""
        rows: list[dict[str, object]] = []
        for snap in snapshots:
            if not snap.name.startswith("events-"):
                continue
            match_id = int(snap.name.removeprefix("events-").removesuffix(".json"))
            payload = snap.read_json()
            if not isinstance(payload, list):
                raise DataValidationError(f"statsbomb schema changed in {snap.name}")
            for event in payload:
                if not isinstance(event, dict) or not {"id", "type", "team"} <= event.keys():
                    raise DataValidationError(f"statsbomb schema changed in {snap.name}")
                x, y = _xy(event.get("location"), "location")
                pass_ = event.get("pass") or {}
                carry = event.get("carry") or {}
                shot = event.get("shot") or {}
                end_x, end_y = _xy(
                    pass_.get("end_location") or carry.get("end_location"), "end_location"
                )
                rows.append(
                    {
                        "match_id": match_id,
                        "event_id": str(event["id"]),
                        "index": event.get("index"),
                        "period": event.get("period"),
                        "minute": event.get("minute"),
                        "second": event.get("second"),
                        "type": _name(event["type"]),
                        "team_id": _id(event["team"]),
                        "team": _name(event["team"]),
                        "player_id": _id(event.get("player")),
                        "player": _name(event.get("player")),
                        "position": _name(event.get("position")),
                        "x": x,
                        "y": y,
                        "end_x": end_x,
                        "end_y": end_y,
                        "shot_xg": shot.get("statsbomb_xg"),
                        "outcome": _name(shot.get("outcome")),
                        "source": SOURCE,
                        "fetched_at": snap.fetched_at,
                    }
                )
        return pd.DataFrame(rows)
