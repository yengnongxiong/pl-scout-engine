"""Orchestrates ``scout ingest``: fetch raw snapshots and validate them per source.

FPL runs first because it defines the current season (CLAUDE.md rule 7) and the clubs in
it; every other source derives its seasons and club list from the newest FPL
``bootstrap-static`` snapshot. Each source is fetched, then parsed immediately so a schema
change fails during ingest rather than later in ``scout build``. One failing source does
not stop the others; the caller decides the exit code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from scout.config import AppConfig, Settings
from scout.errors import ConfigError, ScoutError, SourceUnavailableError
from scout.ingest.base import PoliteClient, SnapshotStore, SourceAdapter
from scout.ingest.fotmob import FotMobAdapter
from scout.ingest.fpl import BOOTSTRAP, FplAdapter, FplBootstrap, season_from_events
from scout.ingest.history import VaastavHistoryAdapter, previous_seasons
from scout.ingest.statsbomb import StatsBombAdapter
from scout.ingest.transfermarkt import (
    TransfermarktAdapter,
    TransfermarktDatasetsAdapter,
    normalise_name,
)
from scout.ingest.understat import UnderstatAdapter

logger = logging.getLogger(__name__)

ALL_SOURCES = (
    "fpl",
    "vaastav",
    "understat",
    "fotmob",
    "transfermarkt",
    "transfermarkt_datasets",
    "statsbomb",
)

ReaderFactory = Callable[[str], Any]


@dataclass
class IngestResult:
    """Outcome of ingesting one source."""

    source: str
    ok: bool
    snapshots: int = 0
    rows: int = 0
    requests: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SeasonContext:
    """Facts derived from the newest FPL bootstrap snapshot."""

    current_season: str
    club_names: list[str]


def club_aliases(
    club_names: Sequence[str], aliases: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    """Map each FPL club name to every known spelling (canonical name plus aliases).

    Clubs missing from ``config/team_aliases.yaml`` keep just their FPL name.
    """
    index: dict[str, str] = {}
    for canonical, alts in aliases.items():
        for name in (canonical, *alts):
            index[normalise_name(name)] = canonical
    out: dict[str, list[str]] = {}
    for club in club_names:
        matched = index.get(normalise_name(club))
        spellings = [club]
        if matched is not None:
            spellings += [matched, *aliases[matched]]
        out[club] = list(dict.fromkeys(s for s in spellings if s != club))
    return out


def season_context(store: SnapshotStore) -> SeasonContext:
    """Read the newest FPL bootstrap snapshot for the current season and clubs."""
    snap = store.latest("fpl", BOOTSTRAP)
    if snap is None:
        raise SourceUnavailableError(
            "no FPL bootstrap-static snapshot yet; run `scout ingest --source fpl` first"
        )
    boot: FplBootstrap = FplAdapter.parse_bootstrap(snap)
    return SeasonContext(season_from_events(boot.events), [t.name for t in boot.teams])


def _base_url(config: AppConfig, source: str) -> str:
    url = next((u for s, u in config.settings.ingest.base_urls.items() if s == source), None)
    if not url:
        raise ConfigError(f"ingest.base_urls.{source} is not configured")
    return url


def build_adapter(
    source: str,
    config: AppConfig,
    store: SnapshotStore,
    reader_factories: Mapping[str, ReaderFactory] | None = None,
) -> SourceAdapter:
    """Create the adapter for ``source`` with seasons and clubs derived from FPL."""
    ingest = config.settings.ingest
    factories = reader_factories or {}
    if source == "fpl":
        return FplAdapter(_base_url(config, "fpl"))
    if source == "statsbomb":
        return StatsBombAdapter(
            _base_url(config, "statsbomb"),
            ingest.statsbomb_competition_id,
            ingest.statsbomb_season_id,
            ingest.statsbomb_max_matches,
        )
    if source == "transfermarkt_datasets":
        return TransfermarktDatasetsAdapter(
            _base_url(config, "transfermarkt_datasets"), ingest.tm_datasets_competition_id
        )
    ctx = season_context(store)
    # Blending (PRD §8.2) needs the current and the previous season.
    recent = [ctx.current_season, *previous_seasons(ctx.current_season, 1)]
    if source == "vaastav":
        seasons = previous_seasons(ctx.current_season, ingest.history_seasons_back)
        return VaastavHistoryAdapter(_base_url(config, "vaastav"), seasons)
    if source == "understat":
        return UnderstatAdapter(recent, reader_factory=factories.get("understat"))
    if source == "fotmob":
        return FotMobAdapter(
            recent, ingest.possession_sum_tolerance, reader_factory=factories.get("fotmob")
        )
    if source == "transfermarkt":
        clubs = club_aliases(ctx.club_names, config.team_aliases.aliases)
        return TransfermarktAdapter(_base_url(config, "transfermarkt"), clubs)
    raise ConfigError(f"unknown source {source!r}; choose from {', '.join(ALL_SOURCES)}")


def run_ingest(
    sources: Sequence[str],
    settings: Settings,
    config: AppConfig,
    *,
    max_requests: int | None = None,
    transport: httpx.BaseTransport | None = None,
    reader_factories: Mapping[str, ReaderFactory] | None = None,
) -> list[IngestResult]:
    """Fetch and validate each source in dependency order (FPL first)."""
    wanted = list(ALL_SOURCES) if "all" in sources else list(dict.fromkeys(sources))
    unknown = [s for s in wanted if s not in ALL_SOURCES]
    if unknown:
        raise ConfigError(f"unknown source(s) {unknown}; choose from {', '.join(ALL_SOURCES)}")
    ordered = sorted(wanted, key=ALL_SOURCES.index)
    store = SnapshotStore(settings.data_dir / "raw")
    results: list[IngestResult] = []
    for source in ordered:
        result = IngestResult(source=source, ok=False)
        try:
            adapter = build_adapter(source, config, store, reader_factories)
            with PoliteClient(
                source, config.settings.ingest, transport=transport, max_requests=max_requests
            ) as client:
                try:
                    snapshots = adapter.fetch(client, store)
                finally:
                    result.requests = client.requests_made
            frame = adapter.parse(snapshots)
            result.ok, result.snapshots, result.rows = True, len(snapshots), len(frame)
            if isinstance(adapter, TransfermarktAdapter) and adapter.unmatched_clubs:
                result.notes.append(f"unmatched clubs: {', '.join(adapter.unmatched_clubs)}")
        except ScoutError as exc:
            result.error = exc.message
            logger.error("ingest failed", extra={"source": source, "error": exc.message})
        results.append(result)
    return results
