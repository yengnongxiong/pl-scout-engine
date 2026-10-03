"""``scout doctor``: freshness, coverage and validation status (PRD §14 observability).

Reads only local state (warehouse, raw snapshots, last build summary) and never calls a
source, so it is safe to run any time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scout.config import AppConfig, Settings
from scout.db.build import last_build_path
from scout.db.models import DimPlayer, EntityMapReview, FactPlayerMatch, SourceSnapshot
from scout.db.session import make_engine, make_session_factory
from scout.errors import DataValidationError
from scout.ingest.base import SnapshotStore
from scout.ingest.fpl import BOOTSTRAP, FplAdapter


@dataclass
class SourceFreshness:
    """Newest snapshot per source and whether it is stale."""

    source: str
    last_fetched: datetime
    age_hours: float
    stale: bool


@dataclass
class DoctorReport:
    """Everything ``scout doctor`` prints."""

    warehouse_exists: bool
    freshness: list[SourceFreshness] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)
    review_count: int = 0
    last_build: dict[str, object] | None = None
    fpl_schema: str = "not checked"
    warnings: list[str] = field(default_factory=list)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything is stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def freshness(session: Session, config: AppConfig, now: datetime) -> list[SourceFreshness]:
    """Newest ``source_snapshot`` per source with an age-based stale flag."""
    rows = session.execute(
        select(SourceSnapshot.source, func.max(SourceSnapshot.fetched_at)).group_by(
            SourceSnapshot.source
        )
    ).all()
    out: list[SourceFreshness] = []
    for source, last in sorted(rows):
        last_dt = _aware(last)
        age = (now - last_dt).total_seconds() / 3600
        out.append(
            SourceFreshness(source, last_dt, age, age > config.settings.doctor.threshold(source))
        )
    return out


def minutes_coverage(session: Session) -> dict[str, float]:
    """Share of FPL minutes played by players linked to Understat and Transfermarkt."""
    rows = session.execute(
        select(DimPlayer.understat_id, DimPlayer.tm_id, func.sum(FactPlayerMatch.minutes))
        .join(FactPlayerMatch, FactPlayerMatch.player_id == DimPlayer.player_id)
        .where(FactPlayerMatch.source == "fpl")
        .group_by(DimPlayer.player_id, DimPlayer.understat_id, DimPlayer.tm_id)
    ).all()
    total = sum(m or 0 for _, _, m in rows)
    if total == 0:
        return {}
    return {
        "understat": sum(m or 0 for us, _, m in rows if us is not None) / total,
        "transfermarkt": sum(m or 0 for _, tm, m in rows if tm is not None) / total,
    }


def check_fpl_schema(settings: Settings) -> str:
    """Validate the newest FPL bootstrap snapshot and describe any missing fields."""
    snap = SnapshotStore(settings.data_dir / "raw").latest("fpl", BOOTSTRAP)
    if snap is None:
        return "no FPL snapshot yet (run `scout ingest --source fpl`)"
    try:
        FplAdapter.parse_bootstrap(snap)
    except DataValidationError as exc:
        errors = exc.details.get("errors")
        fields: set[str] = set()
        if isinstance(errors, list):
            for err in errors:
                if isinstance(err, dict):
                    fields.add(".".join(str(part) for part in err.get("loc", ())))
        listed = ", ".join(sorted(fields)) or "unknown"
        return f"SCHEMA CHANGED: {exc.message}; fields: {listed}"
    return f"ok (snapshot {snap.fetched_at:%Y-%m-%d %H:%M} UTC)"


def run_doctor(settings: Settings, config: AppConfig, now: datetime | None = None) -> DoctorReport:
    """Collect freshness, coverage, review and validation status."""
    now = now or datetime.now(UTC)
    db_url = settings.database_url
    exists = not db_url.startswith("sqlite:///") or (
        db_url == "sqlite:///:memory:" or _sqlite_path_exists(db_url)
    )
    report = DoctorReport(warehouse_exists=exists)
    report.fpl_schema = check_fpl_schema(settings)
    if report.fpl_schema.startswith("SCHEMA CHANGED"):
        report.warnings.append("FPL schema changed: update the adapter before the next build")
    path = last_build_path(settings)
    if path.exists():
        report.last_build = json.loads(path.read_text(encoding="utf-8"))
        if report.last_build and not report.last_build.get("validation_ok", True):
            report.warnings.append("last build had validation failures (--allow-invalid)")
    if not exists:
        report.warnings.append("no warehouse yet: run `scout build`")
        return report
    engine = make_engine(db_url)
    with make_session_factory(engine)() as session:
        report.freshness = freshness(session, config, now)
        report.coverage = minutes_coverage(session)
        report.review_count = session.scalar(select(func.count()).select_from(EntityMapReview)) or 0
    engine.dispose()
    target = config.settings.entity_resolution.target_minutes_coverage
    report.warnings += [
        f"{f.source} is stale ({f.age_hours:.0f} h old)" for f in report.freshness if f.stale
    ]
    report.warnings += [
        f"{source} coverage {share:.1%} below target {target:.0%}"
        for source, share in report.coverage.items()
        if share < target
    ]
    return report


def _sqlite_path_exists(url: str) -> bool:
    return Path(url.removeprefix("sqlite:///")).exists()
