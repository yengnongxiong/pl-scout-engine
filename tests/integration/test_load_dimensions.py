from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scout.config import PROJECT_ROOT, load_config
from scout.db.load import DimensionLoader
from scout.db.models import Base, DimMatch, DimPlayer, DimSeason, DimTeam
from scout.db.session import make_engine, make_session_factory
from scout.ingest.base import SnapshotStore
from scout.ingest.fotmob import FotMobAdapter
from scout.ingest.fotmob import snapshot_name as fotmob_name
from scout.ingest.fpl import BOOTSTRAP, FIXTURES, FplAdapter, element_summary_name
from scout.ingest.understat import KINDS, UnderstatAdapter
from scout.ingest.understat import snapshot_name as us_name

FIX = PROJECT_ROOT / "tests" / "fixtures"
CFG = load_config(PROJECT_ROOT / "config")


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def staged(tmp_path: Path) -> dict[str, pd.DataFrame]:
    store = SnapshotStore(tmp_path, clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    fpl_snaps = [
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
    us_snaps = [
        store.write(
            "understat",
            us_name("2025-26", k),
            (FIX / f"understat/synthetic_{us_name('2025-26', k)}").read_bytes(),
        )
        for k in KINDS
    ]
    fm_snap = store.write(
        "fotmob",
        fotmob_name("2025-26"),
        (FIX / f"fotmob/synthetic_{fotmob_name('2025-26')}").read_bytes(),
    )
    fpl = FplAdapter("https://fpl.test/")
    return {
        "teams": fpl.parse_teams(fpl_snaps),
        "players": fpl.parse_players(fpl_snaps),
        "fixtures": fpl.parse_fixtures(fpl_snaps),
        "us_team_match": UnderstatAdapter(["2025-26"]).parse_team_match(us_snaps),
        "possession": FotMobAdapter(["2025-26"], 0.02).parse([fm_snap]),
    }


def _count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _load(session: Session, staged: dict[str, pd.DataFrame]) -> dict[str, dict[object, int]]:
    loader = DimensionLoader(session)
    loader.season("2026-27", is_current=True)
    team_ids = loader.teams_from_fpl(staged["teams"], CFG.team_aliases.aliases)
    fixture_ids = loader.matches_from_fpl(staged["fixtures"], team_ids)
    club_codes = {"Synthetic Rovers": 9001, "Fixture Town": 9002}
    us_ids = loader.matches_from_understat(staged["us_team_match"], club_codes)
    lookup = {
        name: session.scalars(select(DimTeam.team_id).where(DimTeam.name == name)).one()
        for name in club_codes
    }
    fm_ids = loader.matches_from_fotmob(staged["possession"], lookup)
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
                "understat_id": "8802",
                "transfermarkt_id": None,
            },
            {
                "fpl_code": 500013,
                "canonical_name": "Cy Benchley",
                "understat_id": None,
                "transfermarkt_id": "880013",
            },
        ]
    )
    tm = pd.DataFrame(
        [
            {
                "tm_player_id": "880011",
                "tm_position": "Centre-Back",
                "birth_date": date(1998, 3, 14),
            },
            {"tm_player_id": "880013", "tm_position": "Central Midfield", "birth_date": None},
        ]
    )
    player_ids = loader.players(mapping, staged["players"], tm, CFG.positions)
    session.commit()
    return {
        "teams": dict(team_ids),
        "fixtures": dict(fixture_ids),
        "understat": dict(us_ids),
        "fotmob": dict(fm_ids),
        "players": dict(player_ids),
    }


def test_dimensions_load_and_link_sources(
    session: Session, staged: dict[str, pd.DataFrame]
) -> None:
    ids = _load(session, staged)
    assert _count(session, DimTeam) == 2  # understat clubs linked, not duplicated
    rovers = session.scalars(select(DimTeam).where(DimTeam.fpl_code == 9001)).one()
    assert rovers.understat_id == 71
    assert _count(session, DimMatch) == 3 + 2  # 3 FPL fixtures (2026-27) + 2 understat (2025-26)
    seasons = {s.season_id: s.is_current for s in session.scalars(select(DimSeason))}
    assert seasons == {"2026-27": True, "2025-26": False}
    assert set(ids["understat"]) == {9101, 9102}
    # FotMob: first two games link to understat matches; the unknown club is skipped.
    assert set(ids["fotmob"]) == {
        "2025-08-16 Synthetic Rovers-Fixture Town",
        "2025-08-23 Fixture Town-Synthetic Rovers",
    }
    assert ids["fotmob"]["2025-08-16 Synthetic Rovers-Fixture Town"] == ids["understat"][9101]


def test_players_get_position_groups(session: Session, staged: dict[str, pd.DataFrame]) -> None:
    ids = _load(session, staged)
    alex = session.get(DimPlayer, ids["players"][500011])
    bo = session.get(DimPlayer, ids["players"][500012])
    cy = session.get(DimPlayer, ids["players"][500013])
    assert alex is not None and bo is not None and cy is not None
    assert (alex.position_group, alex.detailed_position) == ("CB", "Centre-Back")
    assert alex.birth_date == date(1998, 3, 14) and alex.tm_id == "880011"
    assert alex.understat_id == 8801
    assert bo.position_group == "ST"  # no TM record → FPL FWD fallback
    assert cy.position_group == "CM" and cy.birth_date is None


def test_reload_is_idempotent(session: Session, staged: dict[str, pd.DataFrame]) -> None:
    first = _load(session, staged)
    counts = [_count(session, m) for m in (DimTeam, DimMatch, DimPlayer, DimSeason)]
    second = _load(session, staged)
    assert [_count(session, m) for m in (DimTeam, DimMatch, DimPlayer, DimSeason)] == counts
    assert first == second
