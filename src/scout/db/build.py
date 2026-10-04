"""``scout build``: raw snapshots → validated silver tables → warehouse (PRD §10).

Steps: parse the newest snapshot of every file per source, validate every staged table
(a failure stops the build unless ``--allow-invalid``, CLAUDE.md rule 12), resolve
players across sources, migrate the database to the latest schema, then load dimensions
and facts in one transaction so a failed build never leaves a half-written warehouse.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from scout.config import PROJECT_ROOT, AppConfig, Settings
from scout.db.load import DimensionLoader, FactLoader
from scout.db.models import DimTeam
from scout.db.session import make_engine, make_session_factory
from scout.errors import SourceUnavailableError
from scout.ingest.base import RawSnapshot, SnapshotStore
from scout.ingest.fotmob import FotMobAdapter
from scout.ingest.fpl import FplAdapter
from scout.ingest.history import VaastavHistoryAdapter
from scout.ingest.transfermarkt import (
    TransfermarktAdapter,
    TransfermarktDatasetsAdapter,
    load_market_value_overrides,
)
from scout.ingest.understat import UnderstatAdapter
from scout.transform.entity_resolution import (
    SourceRecord,
    fpl_anchors,
    load_player_overrides,
    map_clubs,
    resolve,
    transfermarkt_records,
    understat_records,
)
from scout.transform.validate import ValidationReport, enforce, validate_tables

logger = logging.getLogger(__name__)

_SEASON_PREFIX = re.compile(r"^(\d{4}-\d{2})_")


@dataclass
class BuildReport:
    """What a build did, for the CLI and ``scout doctor``."""

    sources: list[str] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)
    coverage: str = ""
    review_count: int = 0
    written: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


def seasons_in(snapshots: Sequence[RawSnapshot]) -> list[str]:
    """Seasons present in season-prefixed snapshot names, newest first."""
    seasons = {m.group(1) for s in snapshots if (m := _SEASON_PREFIX.match(s.name))}
    return sorted(seasons, reverse=True)


def migrate(database_url: str) -> None:
    """Upgrade the warehouse schema to the latest Alembic revision."""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def build_warehouse(
    settings: Settings, config: AppConfig, *, allow_invalid: bool = False
) -> BuildReport:
    """Run the full raw → warehouse build from the newest local snapshots."""
    report = BuildReport()
    store = SnapshotStore(settings.data_dir / "raw")
    fpl_snaps = store.latest_all("fpl")
    if not fpl_snaps:
        raise SourceUnavailableError("no FPL snapshots; run `scout ingest --source fpl` first")
    fpl = FplAdapter("")
    teams, players = fpl.parse_teams(fpl_snaps), fpl.parse_players(fpl_snaps)
    fixtures, fpl_pm = fpl.parse_fixtures(fpl_snaps), fpl.parse(fpl_snaps)
    current_season = str(teams["season_id"].iloc[0])
    report.sources.append("fpl")
    frames: dict[str, pd.DataFrame] = {"fpl_player_match": fpl_pm}

    va_snaps = store.latest_all("vaastav")
    history: pd.DataFrame | None = None
    if va_snaps:
        history = VaastavHistoryAdapter("", seasons_in(va_snaps)).parse(va_snaps)
        frames["vaastav_player_match"] = history
        report.sources.append("vaastav")

    us_snaps = store.latest_all("understat")
    us_pm: pd.DataFrame | None = None
    us_tm: pd.DataFrame | None = None
    if us_snaps:
        understat = UnderstatAdapter(seasons_in(us_snaps))
        us_pm, us_tm = understat.parse(us_snaps), understat.parse_team_match(us_snaps)
        frames["understat_player_match"], frames["understat_team_match"] = us_pm, us_tm
        report.sources.append("understat")

    fm_snaps = store.latest_all("fotmob")
    possession: pd.DataFrame | None = None
    if fm_snaps:
        tolerance = config.settings.ingest.possession_sum_tolerance
        possession = FotMobAdapter(seasons_in(fm_snaps), tolerance).parse(fm_snaps)
        frames["fotmob_possession"] = possession
        report.sources.append("fotmob")

    tm_frames: list[pd.DataFrame] = []
    tm_snaps = store.latest_all("transfermarkt")
    tm_live = TransfermarktAdapter("", {}).parse(tm_snaps) if tm_snaps else None
    if tm_live is not None and not tm_live.empty:
        tm_frames.append(tm_live)
        report.sources.append("transfermarkt")
    ds_snaps = store.latest_all("transfermarkt_datasets")
    tm_stale: pd.DataFrame | None = None
    tm_history: pd.DataFrame | None = None
    if ds_snaps:
        competition = config.settings.ingest.tm_datasets_competition_id
        datasets = TransfermarktDatasetsAdapter("", competition)
        # Player details (names, positions, DOB) feed entity resolution; the full
        # valuation history is what gets stored (stale fallback + value-model labels).
        tm_stale, tm_history = datasets.parse(ds_snaps), datasets.parse_history(ds_snaps)
        tm_frames.append(tm_history)
        report.sources.append("transfermarkt_datasets")
    if tm_frames:
        frames["tm_market_value"] = pd.concat(tm_frames, ignore_index=True)

    report.validation = validate_tables(frames, config.settings.validation)
    enforce(report.validation, allow_invalid=allow_invalid)

    # Entity resolution: live Transfermarkt squads if present, else the stale snapshot.
    tm_for_er = tm_live if tm_live is not None and not tm_live.empty else tm_stale
    fpl_teams = dict(zip(teams["fpl_code"], teams["name"], strict=True))
    if history is not None:
        # Past-season clubs (e.g. relegated) keep their stable FPL team code.
        for code, name in zip(history["opponent_fpl_code"], history["opponent_name"], strict=True):
            fpl_teams.setdefault(int(code), str(name))
    source_clubs: set[str] = set()
    if us_pm is not None:
        source_clubs |= {str(c) for c in us_pm["team_name"]}
    if us_tm is not None:
        source_clubs |= {str(c) for c in us_tm["team_name"]}
        source_clubs |= {str(c) for c in us_tm["opponent_name"]}
    if tm_for_er is not None:
        source_clubs |= {str(c) for c in tm_for_er["tm_club_name"].dropna()}
    if possession is not None:
        source_clubs |= set(possession["team_name"])
    clubs = map_clubs(source_clubs, fpl_teams, config.team_aliases.aliases)
    anchors = fpl_anchors(players, fpl_pm)
    records: list[SourceRecord] = []
    if us_pm is not None:
        records += understat_records(us_pm, clubs)
    if tm_for_er is not None:
        records += transfermarkt_records(tm_for_er, clubs)
    overrides_dir = settings.data_dir / "overrides"
    player_overrides = overrides_dir / "player_overrides.csv"
    forced = load_player_overrides(player_overrides) if player_overrides.exists() else {}
    resolution = resolve(anchors, records, config.settings.entity_resolution, forced)
    report.coverage = resolution.coverage_report(
        config.settings.entity_resolution.target_minutes_coverage
    )
    report.review_count = len(resolution.review)
    mapping = resolution.mapping_frame(anchors)

    migrate(settings.database_url)
    engine = make_engine(settings.database_url)
    now = datetime.now(UTC)
    with make_session_factory(engine)() as session, session.begin():
        dims = DimensionLoader(session)
        dims.season(current_season, is_current=True)
        team_ids = dims.teams_from_fpl(teams, config.team_aliases.aliases)
        fixture_ids = dims.matches_from_fpl(fixtures, team_ids)
        player_ids = dims.players(mapping, players, tm_for_er, config.positions)
        facts = FactLoader(session)
        facts.player_match_fpl(fpl_pm, player_ids, fixture_ids, team_ids)
        facts.player_status(players, player_ids, _contracts(mapping, tm_for_er))
        facts.snapshots(fpl_snaps, "ok", len(fpl_pm))

        if history is not None:
            vaastav_matches = dims.matches_from_vaastav(history)
            all_codes = {
                t.fpl_code: t.team_id
                for t in session.scalars(select(DimTeam))
                if t.fpl_code is not None
            }
            facts.player_match_vaastav(history, player_ids, vaastav_matches, all_codes)
            facts.snapshots(va_snaps, "ok", len(history))
        team_by_code = {
            t.fpl_code: t.team_id for t in session.scalars(select(DimTeam)) if t.fpl_code
        }
        if us_pm is not None and us_tm is not None:
            game_ids = dims.matches_from_understat(us_tm, clubs)
            understat_teams = {
                t.understat_id: t.team_id
                for t in session.scalars(select(DimTeam))
                if t.understat_id is not None
            }
            us_players = _source_ids(mapping, "understat_id", player_ids, int)
            facts.player_match_understat(us_pm, us_players, game_ids, understat_teams)
            facts.team_match_understat(us_tm, game_ids, understat_teams)
            facts.snapshots(us_snaps, "ok", len(us_pm))
        if possession is not None:
            name_to_team = {
                name: team_by_code[code]
                for name, code in clubs.items()
                if code is not None and code in team_by_code
            }
            game_keys = dims.matches_from_fotmob(possession, name_to_team)
            facts.team_possession_fotmob(possession, game_keys, name_to_team)
            facts.snapshots(fm_snaps, "ok", len(possession))
        tm_players = _source_ids(mapping, "transfermarkt_id", player_ids, str)
        values = [f for f in (tm_live, tm_history) if f is not None and not f.empty]
        overrides_file = overrides_dir / "market_value_overrides.csv"
        if overrides_file.exists():
            values.append(load_market_value_overrides(overrides_file))
        if values:
            facts.market_values(pd.concat(values, ignore_index=True), tm_players)
        facts.snapshots(tm_snaps + ds_snaps, "ok", None)
        facts.review(resolution.review, player_ids, now)
        report.written, report.skipped = dict(facts.stats.written), dict(facts.stats.skipped)
    engine.dispose()
    write_last_build(settings, report, now)
    logger.info("build complete", extra={"sources": report.sources})
    return report


def last_build_path(settings: Settings) -> Path:
    """Where the latest build summary is stored (read by ``scout doctor``)."""
    return settings.data_dir / "warehouse" / "last_build.json"


def write_last_build(settings: Settings, report: BuildReport, when: datetime) -> None:
    """Persist a small JSON summary of the build for ``scout doctor``."""
    path = last_build_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built_at": when.isoformat(),
        "sources": report.sources,
        "validation_ok": report.validation.ok,
        "validation_summary": report.validation.summary(),
        "coverage": report.coverage,
        "review_count": report.review_count,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _source_ids[K: (int, str)](
    mapping: pd.DataFrame, column: str, player_ids: dict[int, int], cast: type[K]
) -> dict[K, int]:
    out: dict[K, int] = {}
    for rec in mapping.to_dict(orient="records"):
        value = rec.get(column)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        out[cast(value)] = player_ids[int(rec["fpl_code"])]
    return out


def _contracts(mapping: pd.DataFrame, tm: pd.DataFrame | None) -> dict[int, date | None]:
    if tm is None or tm.empty:
        return {}
    expiry: dict[str, date | None] = {}
    for r in tm.to_dict(orient="records"):
        value = r.get("contract_expiry")
        expiry[str(r["tm_player_id"])] = value if isinstance(value, date) else None
    out: dict[int, date | None] = {}
    for rec in mapping.to_dict(orient="records"):
        tm_id = rec.get("transfermarkt_id")
        if isinstance(tm_id, str) and tm_id in expiry:
            out[int(rec["fpl_code"])] = expiry[tm_id]
    return out
