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
from scout.db.queries import season_bounds
from scout.db.session import make_engine, make_session_factory
from scout.ingest.base import SnapshotStore
from scout.ingest.espn import EspnAdapter
from scout.ingest.espn import snapshot_name as espn_name
from scout.ingest.fpl import BOOTSTRAP, FIXTURES, FplAdapter, element_summary_name
from scout.ingest.history import VaastavHistoryAdapter
from scout.ingest.history import snapshot_names as vaastav_names
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
        "espn",
        espn_name("2025-26"),
        (FIX / f"espn/synthetic_{espn_name('2025-26')}").read_bytes(),
    )
    fpl = FplAdapter("https://fpl.test/")
    return {
        "teams": fpl.parse_teams(fpl_snaps),
        "players": fpl.parse_players(fpl_snaps),
        "fixtures": fpl.parse_fixtures(fpl_snaps),
        "us_team_match": UnderstatAdapter(["2025-26"]).parse_team_match(us_snaps),
        "possession": EspnAdapter("", ["2025-26"], 0.02).parse([fm_snap]),
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
    fm_ids = loader.matches_from_espn(staged["possession"], lookup)
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
        "espn": dict(fm_ids),
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
    # ESPN: the first two matches link to Understat's; the unknown club's is skipped.
    assert set(ids["espn"]) == {990001, 990002}
    assert ids["espn"][990001] == ids["understat"][9101]


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


def test_birth_date_comes_from_fpl_before_transfermarkt(
    session: Session, staged: dict[str, pd.DataFrame]
) -> None:
    players = staged["players"].copy()
    players["birth_date"] = players["fpl_code"].map({500012: date(2001, 5, 2)})
    players["birth_date"] = (
        players["birth_date"].astype(object).where(players["birth_date"].notna(), None)
    )
    ids = _load(session, {**staged, "players": players})
    bo = session.get(DimPlayer, ids["players"][500012])
    alex = session.get(DimPlayer, ids["players"][500011])
    assert bo is not None and alex is not None
    assert bo.birth_date == date(2001, 5, 2)  # FPL only: no Transfermarkt record needed
    assert alex.birth_date == date(1998, 3, 14)  # no FPL date: Transfermarkt's


def test_reload_is_idempotent(session: Session, staged: dict[str, pd.DataFrame]) -> None:
    first = _load(session, staged)
    counts = [_count(session, m) for m in (DimTeam, DimMatch, DimPlayer, DimSeason)]
    second = _load(session, staged)
    assert [_count(session, m) for m in (DimTeam, DimMatch, DimPlayer, DimSeason)] == counts
    assert first == second


def test_vaastav_matches_carry_kickoff_and_scores(tmp_path: Path) -> None:
    # Past-season matches exist only through vaastav rows; without their kickoff the season
    # has no end date (so no value-model label), and without scores no league table.
    engine = make_engine(f"sqlite:///{tmp_path / 'w.db'}")
    Base.metadata.create_all(engine)
    store = SnapshotStore(tmp_path / "raw", clock=lambda: datetime(2026, 9, 1, tzinfo=UTC))
    snaps = [
        store.write("vaastav", name, (FIX / f"vaastav/synthetic_{name}").read_bytes())
        for season in ("2025-26", "2023-24")
        for name in vaastav_names(season)
    ]
    history = VaastavHistoryAdapter("https://archive.test/", ["2025-26", "2023-24"]).parse(snaps)
    with make_session_factory(engine)() as session:
        loader = DimensionLoader(session)
        loader.season("2026-27", is_current=True)
        ids = loader.matches_from_vaastav(history)
        session.commit()
        match = session.get(DimMatch, ids[("2025-26", 301)])
        assert match is not None
        assert match.kickoff is not None
        assert match.kickoff.replace(tzinfo=UTC) == datetime(2025, 8, 16, 14, tzinfo=UTC)
        assert (match.home_score, match.away_score) == (1, 1)
    bounds = season_bounds(engine)
    assert "2025-26" in set(bounds["season_id"])


def test_understat_slot_fills_a_missing_transfermarkt_position(
    session: Session, staged: dict[str, pd.DataFrame]
) -> None:
    # Bo has no Transfermarkt record; FPL only says FWD. Understat's minutes-weighted
    # formation slot is the better fallback before the coarse FPL type.
    loader = DimensionLoader(session)
    loader.season("2026-27", is_current=True)
    mapping = pd.DataFrame(
        [
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
                "transfermarkt_id": None,
            },
        ]
    )
    ids = loader.players(mapping, staged["players"], None, CFG.positions, {8802: "W"})
    bo = session.get(DimPlayer, ids[500012])
    cy = session.get(DimPlayer, ids[500013])
    assert bo is not None and cy is not None
    assert bo.position_group == "W" and bo.detailed_position is None
    assert cy.position_group == "CM"  # no Understat slot either: FPL MID fallback
