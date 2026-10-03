import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.errors import DataValidationError
from scout.ingest.base import SnapshotStore
from scout.ingest.fpl import BOOTSTRAP, FIXTURES, FplAdapter, element_summary_name
from scout.ingest.transfermarkt import (
    TransfermarktAdapter,
    club_players_name,
    club_search_name,
    market_value_name,
)
from scout.ingest.understat import KINDS, UnderstatAdapter, snapshot_name
from scout.transform.entity_resolution import (
    AnchorPlayer,
    Link,
    SourceRecord,
    fpl_anchors,
    load_player_overrides,
    map_clubs,
    name_score,
    resolve,
    transfermarkt_records,
    understat_records,
)

CFG = load_config(PROJECT_ROOT / "config").settings.entity_resolution
FIX = PROJECT_ROOT / "tests" / "fixtures"
ROVERS, TOWN = 9001, 9002

ANCHORS = [
    AnchorPlayer(500011, ("Alex Testman", "Testman"), ROVERS, 180.0),
    AnchorPlayer(500013, ("Cy Benchley", "Benchley"), ROVERS, 90.0, date(2000, 1, 1)),
    AnchorPlayer(500020, ("Dan Ward", "Ward"), ROVERS, 90.0),
    AnchorPlayer(500012, ("Bo Fakeson", "Fakeson"), TOWN, 95.0),
    AnchorPlayer(500022, ("Son Heung-min", "Son"), TOWN, 45.0),
]


def rec(source: str, sid: str, name: str, *teams: int, dob: date | None = None) -> SourceRecord:
    return SourceRecord(source, sid, name, frozenset(teams), team_label="club", birth_date=dob)


def links_by_id(links: list[Link]) -> dict[str, int]:
    return {f"{lk.source}:{lk.source_id}": lk.fpl_code for lk in links}


def test_name_score_handles_order_accents_and_web_names() -> None:
    assert name_score(("Son Heung-min", "Son"), "Heung-Min Son") == 100.0
    assert name_score(("Martin Odegaard",), "Martin Ødegaard") == 100.0
    assert name_score(("Bo Fakeson", "Fakeson"), "Fakeson") == 100.0
    assert name_score(("Dan Ward",), "Daniel Ward") < CFG.accept_score


def test_map_clubs_uses_aliases() -> None:
    fpl = {1: "Man City", 2: "Spurs"}
    aliases = {"Manchester City": ["Man City"], "Tottenham Hotspur": ["Spurs", "Tottenham"]}
    assert map_clubs(["Manchester City", "Tottenham", "Wolves"], fpl, aliases) == {
        "Manchester City": 1,
        "Tottenham": 2,
        "Wolves": None,
    }


def test_resolve_accepts_confident_matches_and_reviews_the_rest() -> None:
    records = [
        rec("understat", "1", "Alex Testman", ROVERS),
        rec("understat", "2", "Fakeson", TOWN),
        rec("understat", "3", "Daniel Ward", ROVERS),  # below threshold
        rec("transfermarkt", "t1", "Heung-Min Son", TOWN),
        rec("transfermarkt", "t2", "Cy Benchley", ROVERS, dob=date(1999, 1, 1)),  # DOB veto
        rec("transfermarkt", "t3", "Nobody Known"),  # no club block
    ]
    result = resolve(ANCHORS, records, CFG)
    assert links_by_id(result.links) == {
        "understat:1": 500011,
        "understat:2": 500012,
        "transfermarkt:t1": 500022,
    }
    reasons = {r.source_id: r.reason for r in result.review}
    assert "below" in reasons["3"]
    assert reasons["t2"] == "date of birth mismatch"
    assert reasons["t3"] == "no FPL players at this club"
    ward = next(r for r in result.review if r.source_id == "3")
    assert ward.best_candidate == 500020  # best guess is shown, not applied


def test_ambiguous_candidates_go_to_review() -> None:
    anchors = [*ANCHORS, AnchorPlayer(500030, ("Jon Ward", "Ward"), ROVERS, 10.0)]
    # "Ward" matches both web names exactly: a tie must never be guessed.
    result = resolve(anchors, [rec("understat", "9", "Ward", ROVERS)], CFG)
    assert not result.links
    assert "ambiguous" in result.review[0].reason


def test_duplicate_claims_keep_best_and_review_loser() -> None:
    records = [
        rec("understat", "1", "Alex Testman", ROVERS),
        rec("understat", "7", "Alex Testmann", ROVERS),
    ]
    result = resolve(ANCHORS, records, CFG)
    assert links_by_id(result.links) == {"understat:1": 500011}
    assert [r.source_id for r in result.review] == ["7"]
    assert "same FPL player" in result.review[0].reason


def test_override_wins_over_fuzzy_match() -> None:
    records = [
        rec("understat", "1", "Alex Testman", ROVERS),
        rec("understat", "99", "A. T.", ROVERS),
    ]
    result = resolve(ANCHORS, records, CFG, overrides={("understat", "99"): 500011})
    assert links_by_id(result.links) == {"understat:99": 500011}
    assert result.links[0].method == "override"
    assert [r.source_id for r in result.review] == ["1"]


def test_override_to_unknown_player_rejected() -> None:
    with pytest.raises(DataValidationError, match="unknown fpl_code"):
        resolve(ANCHORS, [rec("understat", "5", "X", ROVERS)], CFG, {("understat", "5"): 1})


def test_coverage_is_minutes_weighted() -> None:
    records = [rec("understat", "1", "Alex Testman", ROVERS)]
    result = resolve(ANCHORS, records, CFG)
    total = sum(a.minutes for a in ANCHORS)
    assert result.coverage["understat"] == pytest.approx(180.0 / total)
    assert result.coverage["transfermarkt"] == 0.0
    assert "BELOW TARGET" in result.coverage_report(CFG.target_minutes_coverage)


def test_mapping_frame_has_null_for_unlinked() -> None:
    result = resolve(ANCHORS, [rec("understat", "1", "Alex Testman", ROVERS)], CFG)
    frame = result.mapping_frame(ANCHORS).set_index("fpl_code")
    assert frame.loc[500011, "understat_id"] == "1"
    assert pd.isna(frame.loc[500012, "understat_id"])


def test_player_overrides_file(tmp_path: Path) -> None:
    committed = load_player_overrides(PROJECT_ROOT / "data/overrides/player_overrides.csv")
    assert committed == {}
    path = tmp_path / "o.csv"
    path.write_text("fpl_code,source,source_id,reason,date\n500011,understat,99,typo,2026-09-01\n")
    assert load_player_overrides(path) == {("understat", "99"): 500011}
    path.write_text("fpl_code,source,source_id,reason,date\n500011,understat,99,,2026-09-01\n")
    with pytest.raises(DataValidationError, match="line 2"):
        load_player_overrides(path)


def test_end_to_end_on_adapter_fixtures(tmp_path: Path) -> None:
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
    fpl = FplAdapter("https://fpl.test/")
    teams = fpl.parse_teams(fpl_snaps)
    anchors = fpl_anchors(fpl.parse_players(fpl_snaps), fpl.parse(fpl_snaps))

    us_snaps = [
        store.write(
            "understat",
            snapshot_name("2025-26", k),
            (FIX / f"understat/synthetic_{snapshot_name('2025-26', k)}").read_bytes(),
        )
        for k in KINDS
    ]
    us_pm = UnderstatAdapter(["2025-26"]).parse(us_snaps)

    def tm_json(name: str) -> bytes:
        return json.dumps(
            json.loads((FIX / f"transfermarkt/synthetic_{name}.json").read_text())
        ).encode()

    tm_snaps = [
        store.write("transfermarkt", club_search_name("Synthetic Rovers"), tm_json("club_search")),
        store.write("transfermarkt", club_players_name("99001"), tm_json("club_players")),
        store.write("transfermarkt", market_value_name("880011"), tm_json("market_value_880011")),
        store.write("transfermarkt", market_value_name("880013"), tm_json("market_value_880013")),
    ]
    tm = TransfermarktAdapter("http://tm.test/", {}).parse(tm_snaps)

    fpl_teams = dict(zip(teams["fpl_code"], teams["name"], strict=True))
    aliases = load_config(PROJECT_ROOT / "config").team_aliases.aliases
    club_names = set(us_pm["team_name"]) | set(tm["tm_club_name"].dropna())
    clubs = map_clubs(club_names, fpl_teams, aliases)
    records = understat_records(us_pm, clubs) + transfermarkt_records(tm, clubs)
    result = resolve(anchors, records, CFG)

    assert links_by_id(result.links) == {
        "understat:8801": 500011,
        "understat:8802": 500012,
        "transfermarkt:880011": 500011,
        "transfermarkt:880013": 500013,
    }
    assert result.coverage["understat"] == pytest.approx(1.0)
    assert result.coverage["transfermarkt"] == pytest.approx(180 / 275)
