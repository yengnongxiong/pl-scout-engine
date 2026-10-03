from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scout.config import PROJECT_ROOT, load_config
from scout.db.load import DimensionLoader, FactLoader
from scout.db.models import (
    Base,
    DimTeam,
    EntityMapReview,
    FactMarketValue,
    FactPlayerMatch,
    FactPlayerStatus,
    FactTeamMatch,
    SourceSnapshot,
)
from scout.db.session import make_engine, make_session_factory
from scout.ingest.base import RawSnapshot, SnapshotStore
from scout.ingest.fotmob import FotMobAdapter
from scout.ingest.fotmob import snapshot_name as fotmob_name
from scout.ingest.fpl import BOOTSTRAP, FIXTURES, FplAdapter, element_summary_name
from scout.ingest.understat import KINDS, UnderstatAdapter
from scout.ingest.understat import snapshot_name as us_name
from scout.transform.entity_resolution import ReviewItem

FIX = PROJECT_ROOT / "tests" / "fixtures"
CFG = load_config(PROJECT_ROOT / "config")
NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def snaps(tmp_path: Path) -> dict[str, list[RawSnapshot]]:
    store = SnapshotStore(tmp_path, clock=lambda: NOW)
    fpl = [
        store.write("fpl", BOOTSTRAP, (FIX / "fpl/synthetic_bootstrap_static.json").read_bytes()),
        store.write("fpl", FIXTURES, (FIX / "fpl/synthetic_fixtures.json").read_bytes()),
    ] + [
        store.write(
            "fpl",
            element_summary_name(i),
            (FIX / f"fpl/synthetic_element_summary_{i}.json").read_bytes(),
        )
        for i in (11, 12)
    ]
    us = [
        store.write(
            "understat",
            us_name("2025-26", k),
            (FIX / f"understat/synthetic_{us_name('2025-26', k)}").read_bytes(),
        )
        for k in KINDS
    ]
    fm = [
        store.write(
            "fotmob",
            fotmob_name("2025-26"),
            (FIX / f"fotmob/synthetic_{fotmob_name('2025-26')}").read_bytes(),
        )
    ]
    return {"fpl": fpl, "understat": us, "fotmob": fm}


def _count(session: Session, model: type[Base], **where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in where.items():
        stmt = stmt.where(getattr(model, col) == val)
    return session.scalar(stmt) or 0


def _build(session: Session, snaps: dict[str, list[RawSnapshot]]) -> FactLoader:
    fpl = FplAdapter("https://fpl.test/")
    teams, players = fpl.parse_teams(snaps["fpl"]), fpl.parse_players(snaps["fpl"])
    fixtures, fpl_pm = fpl.parse_fixtures(snaps["fpl"]), fpl.parse(snaps["fpl"])
    us = UnderstatAdapter(["2025-26"])
    us_pm, us_tm = us.parse(snaps["understat"]), us.parse_team_match(snaps["understat"])
    poss = FotMobAdapter(["2025-26"], 0.02).parse(snaps["fotmob"])

    dims = DimensionLoader(session)
    dims.season("2026-27", is_current=True)
    team_ids = dims.teams_from_fpl(teams, CFG.team_aliases.aliases)
    fixture_ids = dims.matches_from_fpl(fixtures, team_ids)
    club_codes = {"Synthetic Rovers": 9001, "Fixture Town": 9002}
    game_ids = dims.matches_from_understat(us_tm, club_codes)
    names = {t.name: t.team_id for t in session.scalars(select(DimTeam))}
    fotmob_ids = dims.matches_from_fotmob(poss, names)
    mapping = pd.DataFrame(
        [
            {
                "fpl_code": 500011,
                "canonical_name": "Alex Testman",
                "understat_id": "8801",
                "transfermarkt_id": "880011",
            },
            {
                "fpl_code": 500012,
                "canonical_name": "Bo Fakeson",
                "understat_id": None,
                "transfermarkt_id": None,
            },
            {
                "fpl_code": 500013,
                "canonical_name": "Cy Benchley",
                "understat_id": None,
                "transfermarkt_id": None,
            },
        ]
    )
    player_ids = dims.players(mapping, players, None, CFG.positions)
    understat_players = {8801: player_ids[500011]}
    understat_teams = {
        t.understat_id: t.team_id for t in session.scalars(select(DimTeam)) if t.understat_id
    }

    facts = FactLoader(session)
    facts.player_match_fpl(fpl_pm, player_ids, fixture_ids, team_ids)
    facts.player_match_understat(us_pm, understat_players, game_ids, understat_teams)
    facts.team_match_understat(us_tm, game_ids, understat_teams)
    facts.team_possession_fotmob(poss, fotmob_ids, names)
    values = pd.DataFrame(
        [
            {
                "tm_player_id": "880011",
                "value_eur": 32_000_000,
                "tm_last_updated": date(2026, 6, 10),
                "is_stale": False,
                "source": "transfermarkt",
                "fetched_at": NOW,
            },
            {
                "tm_player_id": "999999",
                "value_eur": 1_000_000,
                "tm_last_updated": date(2026, 6, 1),
                "is_stale": False,
                "source": "transfermarkt",
                "fetched_at": NOW,
            },
        ]
    )
    facts.market_values(values, {"880011": player_ids[500011]})
    facts.player_status(players, player_ids, {500011: date(2028, 6, 30)})
    facts.snapshots(snaps["fpl"], "ok", len(fpl_pm))
    facts.review(
        [ReviewItem("understat", "8802", "Bo Fakeson", "Fixture Town", 500012, 80.0, "test")],
        player_ids,
        NOW,
    )
    session.commit()
    return facts


def test_facts_load_per_source(session: Session, snaps: dict[str, list[RawSnapshot]]) -> None:
    facts = _build(session, snaps)
    assert _count(session, FactPlayerMatch, source="fpl") == 4
    # Only Alex is resolved in Understat; Bo's rows are skipped, never guessed.
    assert _count(session, FactPlayerMatch, source="understat") == 1
    assert facts.stats.skipped["fact_player_match:understat"] == 2
    assert _count(session, FactTeamMatch, source="understat") == 4
    assert _count(session, FactTeamMatch, source="fotmob") == 4  # unknown club game skipped
    assert _count(session, FactMarketValue) == 1
    assert facts.stats.skipped["fact_market_value:transfermarkt"] == 1
    assert _count(session, FactPlayerStatus) == 3
    assert _count(session, SourceSnapshot, source="fpl") == 4
    review = session.scalars(select(EntityMapReview)).one()
    assert review.best_candidate is not None


def test_nulls_are_kept_null(session: Session, snaps: dict[str, list[RawSnapshot]]) -> None:
    _build(session, snaps)
    rows = session.scalars(select(FactTeamMatch).where(FactTeamMatch.source == "understat")).all()
    # Game 9102 has no away xG and no shot events → nulls, not zeros.
    assert any(r.xg is None for r in rows)
    assert any(r.set_piece_xg is None for r in rows)
    status = session.scalars(select(FactPlayerStatus)).all()
    assert sum(s.contract_expiry is not None for s in status) == 1
    fpl_rows = session.scalars(select(FactPlayerMatch).where(FactPlayerMatch.source == "fpl"))
    assert all(r.npxg is None and r.shots is None for r in fpl_rows)  # Understat-only columns


def test_reload_replaces_rather_than_duplicates(
    session: Session, snaps: dict[str, list[RawSnapshot]]
) -> None:
    _build(session, snaps)
    before = [_count(session, m) for m in (FactPlayerMatch, FactTeamMatch, FactMarketValue)]
    _build(session, snaps)
    after = [_count(session, m) for m in (FactPlayerMatch, FactTeamMatch, FactMarketValue)]
    assert before == after
    assert _count(session, EntityMapReview) == 1
