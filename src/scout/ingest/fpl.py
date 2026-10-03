"""Fantasy Premier League adapter (PRD §7.1, Tier 1).

Endpoints: ``bootstrap-static/`` (season events, teams, players, availability),
``fixtures/`` and ``element-summary/{id}/`` (per-match history). FPL fields are
undocumented, so every payload is validated against pydantic models and a missing field
raises :class:`~scout.errors.DataValidationError` ("schema changed") instead of silently
producing zeros. FPL ``id`` is reassigned every season, so rows carry the stable ``code``
(CLAUDE.md rule 6). The season string is derived from the events list, never hardcoded
(rule 7).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "fpl"
BOOTSTRAP = "bootstrap-static.json"
FIXTURES = "fixtures.json"


def element_summary_name(element_id: int) -> str:
    """Snapshot file name for one player's ``element-summary`` payload."""
    return f"element-summary-{element_id}.json"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class FplEvent(_Model):
    """A gameweek."""

    id: int
    deadline_time: datetime
    finished: bool


class FplTeam(_Model):
    """A club in the current season."""

    id: int
    code: int
    name: str
    short_name: str


class FplElementType(_Model):
    """FPL position (GKP/DEF/MID/FWD)."""

    id: int
    singular_name_short: str


class FplElement(_Model):
    """A player as listed in ``bootstrap-static``."""

    id: int
    code: int
    first_name: str
    second_name: str
    web_name: str
    team: int
    element_type: int
    status: str
    news: str
    chance_of_playing_next_round: int | None
    minutes: int


class FplBootstrap(_Model):
    """The parts of ``bootstrap-static`` the engine uses."""

    events: list[FplEvent]
    teams: list[FplTeam]
    element_types: list[FplElementType]
    elements: list[FplElement]


class FplFixture(_Model):
    """A fixture; ``event`` and scores are null until scheduled / played."""

    id: int
    code: int
    event: int | None
    kickoff_time: datetime | None
    team_h: int
    team_a: int
    team_h_score: int | None
    team_a_score: int | None
    finished: bool


class FplHistoryRow(_Model):
    """One player-match row from ``element-summary`` ``history``.

    Expected-stat fields arrive as decimal strings; pydantic converts them to float.
    """

    element: int
    fixture: int
    opponent_team: int
    was_home: bool
    kickoff_time: datetime
    round: int
    minutes: int
    starts: int
    goals_scored: int
    assists: int
    expected_goals: float
    expected_assists: float
    expected_goals_conceded: float
    tackles: int
    clearances_blocks_interceptions: int
    recoveries: int
    defensive_contribution: int
    yellow_cards: int
    red_cards: int


class FplElementSummary(_Model):
    """The ``element-summary`` payload (only ``history`` is used)."""

    history: list[FplHistoryRow]


def _validate[M: BaseModel](model: type[M], payload: Any, what: str) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise DataValidationError(
            f"FPL schema changed in {what}: {exc.error_count()} problem(s)",
            details={"errors": exc.errors(include_url=False, include_input=False)},
        ) from exc


def season_from_events(events: Sequence[FplEvent]) -> str:
    """Derive the season id (e.g. ``"2026-27"``) from the gameweek deadlines.

    The season starts in the calendar year of the first gameweek deadline.
    """
    if not events:
        raise DataValidationError("FPL bootstrap-static has no events; cannot derive season")
    start_year = min(e.deadline_time for e in events).year
    return f"{start_year}-{(start_year + 1) % 100:02d}"


class FplAdapter(SourceAdapter):
    """Fetch and parse FPL data."""

    source = SOURCE

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"

    # -- fetch ---------------------------------------------------------------------------

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot bootstrap-static, fixtures, and element-summary for players with minutes."""
        bootstrap_snap = store.write(
            SOURCE, BOOTSTRAP, client.get(self.base_url + "bootstrap-static/")
        )
        snapshots = [bootstrap_snap]
        snapshots.append(store.write(SOURCE, FIXTURES, client.get(self.base_url + "fixtures/")))
        bootstrap = self.parse_bootstrap(bootstrap_snap)
        for element in bootstrap.elements:
            if element.minutes <= 0:
                continue
            url = f"{self.base_url}element-summary/{element.id}/"
            snapshots.append(store.write(SOURCE, element_summary_name(element.id), client.get(url)))
        logger.info("fpl fetch complete", extra={"snapshots": len(snapshots)})
        return snapshots

    # -- parse ---------------------------------------------------------------------------

    @staticmethod
    def parse_bootstrap(snapshot: RawSnapshot) -> FplBootstrap:
        """Validate a ``bootstrap-static`` snapshot."""
        return _validate(FplBootstrap, snapshot.read_json(), "bootstrap-static")

    @staticmethod
    def _find(snapshots: Sequence[RawSnapshot], name: str) -> RawSnapshot:
        for snap in snapshots:
            if snap.name == name:
                return snap
        raise DataValidationError(f"FPL snapshot {name} missing from this run")

    def parse_teams(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Clubs of the current season, keyed on FPL ``code``."""
        snap = self._find(snapshots, BOOTSTRAP)
        boot = self.parse_bootstrap(snap)
        season = season_from_events(boot.events)
        return pd.DataFrame(
            [
                {
                    "fpl_team_id": t.id,
                    "fpl_code": t.code,
                    "name": t.name,
                    "short_name": t.short_name,
                    "season_id": season,
                    "source": SOURCE,
                    "fetched_at": snap.fetched_at,
                }
                for t in boot.teams
            ]
        )

    def parse_players(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Players with FPL position and availability status, keyed on FPL ``code``."""
        snap = self._find(snapshots, BOOTSTRAP)
        boot = self.parse_bootstrap(snap)
        season = season_from_events(boot.events)
        positions = {et.id: et.singular_name_short for et in boot.element_types}
        team_codes = {t.id: t.code for t in boot.teams}
        rows: list[dict[str, object]] = []
        for e in boot.elements:
            if e.element_type not in positions or e.team not in team_codes:
                raise DataValidationError(
                    f"FPL element {e.code} references unknown team/position",
                    details={"team": e.team, "element_type": e.element_type},
                )
            rows.append(
                {
                    "fpl_code": e.code,
                    "fpl_element_id": e.id,
                    "first_name": e.first_name,
                    "second_name": e.second_name,
                    "web_name": e.web_name,
                    "team_fpl_code": team_codes[e.team],
                    "fpl_position": positions[e.element_type],
                    "fpl_status": e.status,
                    "news": e.news or None,
                    "chance_of_playing": e.chance_of_playing_next_round,
                    "season_id": season,
                    "source": SOURCE,
                    "fetched_at": snap.fetched_at,
                }
            )
        return pd.DataFrame(rows)

    def _load_fixtures(
        self, snapshots: Sequence[RawSnapshot], team_codes: dict[int, int]
    ) -> tuple[RawSnapshot, list[FplFixture]]:
        snap = self._find(snapshots, FIXTURES)
        payload = snap.read_json()
        if not isinstance(payload, list):
            raise DataValidationError("FPL schema changed in fixtures: expected a list")
        fixtures = [_validate(FplFixture, f, "fixtures") for f in payload]
        for f in fixtures:
            if f.team_h not in team_codes or f.team_a not in team_codes:
                raise DataValidationError(f"FPL fixture {f.code} references an unknown team")
        return snap, fixtures

    def parse_fixtures(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Fixtures with team FPL codes; unplayed scores stay null."""
        boot = self.parse_bootstrap(self._find(snapshots, BOOTSTRAP))
        season = season_from_events(boot.events)
        team_codes = {t.id: t.code for t in boot.teams}
        snap, fixtures = self._load_fixtures(snapshots, team_codes)
        return pd.DataFrame(
            [
                {
                    "fpl_fixture_code": f.code,
                    "fpl_fixture_id": f.id,
                    "season_id": season,
                    "gameweek": f.event,
                    "kickoff": f.kickoff_time,
                    "home_team_fpl_code": team_codes[f.team_h],
                    "away_team_fpl_code": team_codes[f.team_a],
                    "home_score": f.team_h_score,
                    "away_score": f.team_a_score,
                    "finished": f.finished,
                    "source": SOURCE,
                    "fetched_at": snap.fetched_at,
                }
                for f in fixtures
            ]
        )

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """Player-match rows (``fact_player_match`` FPL columns), keyed on FPL ``code``.

        The player's club for each match is derived from ``was_home`` and the fixture, so a
        player who moved clubs mid-season keeps each match attributed to the right club
        (CLAUDE.md "Known gotchas").
        """
        boot_snap = self._find(snapshots, BOOTSTRAP)
        boot = self.parse_bootstrap(boot_snap)
        season = season_from_events(boot.events)
        codes = {e.id: e.code for e in boot.elements}
        team_codes = {t.id: t.code for t in boot.teams}
        _, fixture_list = self._load_fixtures(snapshots, team_codes)
        fixtures = {f.id: f for f in fixture_list}
        rows: list[dict[str, object]] = []
        for snap in snapshots:
            if not snap.name.startswith("element-summary-"):
                continue
            summary = _validate(FplElementSummary, snap.read_json(), snap.name)
            for h in summary.history:
                if h.element not in codes:
                    raise DataValidationError(f"FPL history row for unknown element {h.element}")
                if h.fixture not in fixtures:
                    raise DataValidationError(f"FPL history row for unknown fixture {h.fixture}")
                if h.opponent_team not in team_codes:
                    raise DataValidationError(f"FPL history row for unknown team {h.opponent_team}")
                fx = fixtures[h.fixture]
                team_id = fx.team_h if h.was_home else fx.team_a
                rows.append(
                    {
                        "fpl_code": codes[h.element],
                        "fpl_fixture_code": fx.code,
                        "season_id": season,
                        "gameweek": h.round,
                        "kickoff": h.kickoff_time,
                        "team_fpl_code": team_codes[team_id],
                        "opponent_fpl_code": team_codes[h.opponent_team],
                        "was_home": h.was_home,
                        "minutes": h.minutes,
                        "started": h.starts > 0,
                        "goals": h.goals_scored,
                        "assists": h.assists,
                        "xg": h.expected_goals,
                        "xa": h.expected_assists,
                        "xgc_on_pitch": h.expected_goals_conceded,
                        "tackles": h.tackles,
                        "cbi": h.clearances_blocks_interceptions,
                        "recoveries": h.recoveries,
                        "def_contribution": h.defensive_contribution,
                        "yellow_cards": h.yellow_cards,
                        "red_cards": h.red_cards,
                        "source": SOURCE,
                        "fetched_at": snap.fetched_at,
                    }
                )
        return pd.DataFrame(rows)
