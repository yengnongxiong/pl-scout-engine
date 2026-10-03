"""Transfermarkt adapter via a self-hosted ``transfermarkt-api`` (PRD §7.1, Tier 1).

Supplies the Transfermarkt estimated market value with Transfermarkt's own as-of date,
detailed position, date of birth and contract expiry. The owner runs
`felipeall/transfermarkt-api` locally; this adapter talks to it politely (≤ 1 request / 3 s
by default, PRD §14). Club ids are found with the API's club search using the club names
and aliases, never hardcoded.

The **as-of date** (``tm_last_updated``) is the date of the latest point in the player's
market-value history: that is when Transfermarkt last revised the valuation, which is the
receipt the UI must show (CLAUDE.md rule 3). A value without any history point has no
receipt and is kept as missing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, NoReturn

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from unidecode import unidecode

from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore, SourceAdapter

logger = logging.getLogger(__name__)

SOURCE = "transfermarkt"
_VALUE_RE = re.compile(r"^€?\s*([\d.,]+)\s*(bn|m|k|th\.)?$", re.IGNORECASE)
_MULTIPLIERS = {"bn": 1_000_000_000, "m": 1_000_000, "k": 1_000, "th.": 1_000}
_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%d.%m.%Y")
_MISSING_TOKENS = frozenset({"", "-", "?", "n/a"})


def parse_market_value(value: object) -> int | None:
    """Parse a Transfermarkt estimated market value into whole euros.

    Accepts integers (``32000000``) and display strings (``"€32.00m"``, ``"€800k"``,
    ``"€1.20bn"``). ``None``, ``"-"`` and empty strings mean not available.

    Raises:
        DataValidationError: If the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise DataValidationError(f"market value {value!r} is not a number")
    if isinstance(value, int):
        return value if value >= 0 else _bad_value(value)
    if isinstance(value, float):
        return round(value) if value >= 0 else _bad_value(value)
    text = str(value).strip()
    if text.casefold() in _MISSING_TOKENS:
        return None
    match = _VALUE_RE.match(text.replace(" ", ""))
    if match is None:
        return _bad_value(value)
    number = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").casefold()
    return round(number * _MULTIPLIERS.get(unit, 1))


def _bad_value(value: object) -> NoReturn:
    raise DataValidationError(f"market value {value!r} is not a Transfermarkt value")


def parse_tm_date(value: object) -> date | None:
    """Parse ISO, ``"Jun 10, 2026"`` or ``"10.06.2026"`` dates; ``None``/``"-"`` → None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text.casefold() in _MISSING_TOKENS:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    raise DataValidationError(f"date {value!r} is not in a known Transfermarkt format")


def normalise_name(name: str) -> str:
    """Accent-free, case-folded, single-spaced name for matching."""
    return " ".join(unidecode(name).casefold().replace("&", "and").split())


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class TmSearchResult(_Model):
    """One club search hit."""

    id: str
    name: str

    @field_validator("id", mode="before")
    @classmethod
    def _id_str(cls, v: object) -> str:
        return str(v)


class TmClubSearch(_Model):
    """``/clubs/search/{name}`` payload."""

    results: list[TmSearchResult]


class TmSquadPlayer(_Model):
    """One player in ``/clubs/{id}/players``."""

    id: str
    name: str
    position: str | None = None
    dateOfBirth: Any = None  # noqa: N815 - API field name
    contract: Any = None
    marketValue: Any = None  # noqa: N815 - API field name

    @field_validator("id", mode="before")
    @classmethod
    def _id_str(cls, v: object) -> str:
        return str(v)


class TmClubPlayers(_Model):
    """``/clubs/{id}/players`` payload."""

    id: str
    players: list[TmSquadPlayer]

    @field_validator("id", mode="before")
    @classmethod
    def _id_str(cls, v: object) -> str:
        return str(v)


class TmValuePoint(_Model):
    """One market-value history point."""

    date: Any
    value: Any = None


class TmMarketValue(_Model):
    """``/players/{id}/market_value`` payload."""

    id: str
    marketValue: Any = None  # noqa: N815 - API field name
    marketValueHistory: list[TmValuePoint]  # noqa: N815 - API field name

    @field_validator("id", mode="before")
    @classmethod
    def _id_str(cls, v: object) -> str:
        return str(v)


def _validate[M: BaseModel](model: type[M], payload: object, what: str) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise DataValidationError(
            f"transfermarkt schema changed in {what}: {exc.error_count()} problem(s)",
            details={"errors": exc.errors(include_url=False, include_input=False)},
        ) from exc


def club_search_name(club: str) -> str:
    """Snapshot name for a club search."""
    return f"club-search-{normalise_name(club).replace(' ', '-')}.json"


def club_players_name(tm_club_id: str) -> str:
    """Snapshot name for a club squad."""
    return f"club-players-{tm_club_id}.json"


def market_value_name(tm_player_id: str) -> str:
    """Snapshot name for one player's market value."""
    return f"market-value-{tm_player_id}.json"


def pick_club(results: Sequence[TmSearchResult], names: Sequence[str]) -> TmSearchResult | None:
    """Return the first search hit whose name exactly matches a club name or alias."""
    wanted = {normalise_name(n) for n in names}
    for result in results:
        if normalise_name(result.name) in wanted:
            return result
    return None


class TransfermarktAdapter(SourceAdapter):
    """Fetch squads and market values from a self-hosted transfermarkt-api."""

    source = SOURCE

    def __init__(self, base_url: str, clubs: Mapping[str, Sequence[str]]) -> None:
        """Create the adapter.

        Args:
            base_url: Root URL of the local transfermarkt-api.
            clubs: Canonical club name → aliases, for the clubs in the current season
                (membership comes from FPL, aliases from ``config/team_aliases.yaml``).
        """
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.clubs = {name: list(aliases) for name, aliases in clubs.items()}
        self.unmatched_clubs: list[str] = []

    def fetch(self, client: PoliteClient, store: SnapshotStore) -> list[RawSnapshot]:
        """Snapshot club search, squad and per-player market value payloads."""
        snapshots: list[RawSnapshot] = []
        self.unmatched_clubs = []
        for club, aliases in self.clubs.items():
            body = client.get(f"{self.base_url}clubs/search/{club}")
            search_snap = store.write(SOURCE, club_search_name(club), body)
            snapshots.append(search_snap)
            search = _validate(TmClubSearch, search_snap.read_json(), search_snap.name)
            hit = pick_club(search.results, [club, *aliases])
            if hit is None:
                logger.warning("transfermarkt club not matched", extra={"club": club})
                self.unmatched_clubs.append(club)
                continue
            squad_body = client.get(f"{self.base_url}clubs/{hit.id}/players")
            squad_snap = store.write(SOURCE, club_players_name(hit.id), squad_body)
            snapshots.append(squad_snap)
            squad = _validate(TmClubPlayers, squad_snap.read_json(), squad_snap.name)
            for player in squad.players:
                mv_body = client.get(f"{self.base_url}players/{player.id}/market_value")
                snapshots.append(store.write(SOURCE, market_value_name(player.id), mv_body))
        return snapshots

    def parse(self, snapshots: Sequence[RawSnapshot]) -> pd.DataFrame:
        """One row per squad player with value, TM as-of date, position, DOB and contract."""
        values: dict[str, tuple[TmMarketValue, RawSnapshot]] = {}
        squads: list[tuple[TmClubPlayers, RawSnapshot]] = []
        for snap in snapshots:
            if snap.name.startswith("market-value-"):
                mv = _validate(TmMarketValue, snap.read_json(), snap.name)
                values[mv.id] = (mv, snap)
            elif snap.name.startswith("club-players-"):
                squads.append((_validate(TmClubPlayers, snap.read_json(), snap.name), snap))
        rows: list[dict[str, object]] = []
        for squad, squad_snap in squads:
            for player in squad.players:
                value_eur, last_updated, fetched_at = self._value(player, values, squad_snap)
                rows.append(
                    {
                        "tm_player_id": player.id,
                        "tm_club_id": squad.id,
                        "name": player.name,
                        "tm_position": player.position or None,
                        "birth_date": parse_tm_date(player.dateOfBirth),
                        "contract_expiry": parse_tm_date(player.contract),
                        "value_eur": value_eur,
                        "tm_last_updated": last_updated,
                        "is_stale": False,
                        "source": SOURCE,
                        "fetched_at": fetched_at,
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _value(
        player: TmSquadPlayer,
        values: Mapping[str, tuple[TmMarketValue, RawSnapshot]],
        squad_snap: RawSnapshot,
    ) -> tuple[int | None, date | None, datetime]:
        entry = values.get(player.id)
        if entry is None:
            # No market-value payload: the squad listing alone has no as-of date.
            return None, None, squad_snap.fetched_at
        mv, snap = entry
        history = [
            (d, parse_market_value(p.value))
            for p in mv.marketValueHistory
            if (d := parse_tm_date(p.date)) is not None
        ]
        if not history:
            return None, None, snap.fetched_at
        last_date, last_value = max(history, key=lambda item: item[0])
        current = parse_market_value(mv.marketValue)
        return (current if current is not None else last_value), last_date, snap.fetched_at
