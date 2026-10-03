import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.dsa.token_bucket import TokenBucket
from scout.errors import DataValidationError
from scout.ingest.base import PoliteClient, RawSnapshot, SnapshotStore
from scout.ingest.transfermarkt import (
    TmSearchResult,
    TransfermarktAdapter,
    club_players_name,
    club_search_name,
    market_value_name,
    normalise_name,
    parse_market_value,
    parse_tm_date,
    pick_club,
)

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "transfermarkt"
FETCHED_AT = datetime(2026, 9, 1, 8, tzinfo=UTC)
BASE = "http://tm.test/"
CLUBS = {"Synthetic Rovers": ["Rovers"]}


def _load(name: str) -> object:
    return json.loads((FIXTURE_DIR / f"synthetic_{name}.json").read_text())


def _payloads() -> dict[str, object]:
    return {
        club_search_name("Synthetic Rovers"): _load("club_search"),
        club_players_name("99001"): _load("club_players"),
        market_value_name("880011"): _load("market_value_880011"),
        market_value_name("880013"): _load("market_value_880013"),
    }


def _snapshots(tmp_path: Path, payloads: dict[str, object]) -> list[RawSnapshot]:
    store = SnapshotStore(tmp_path, clock=lambda: FETCHED_AT)
    return [store.write("transfermarkt", n, json.dumps(p).encode()) for n, p in payloads.items()]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (32000000, 32_000_000),
        (1.5e6, 1_500_000),
        ("€32.00m", 32_000_000),
        ("€800k", 800_000),
        ("€800Th.", 800_000),
        ("€1.20bn", 1_200_000_000),
        ("€ 4.5m", 4_500_000),
        (None, None),
        ("-", None),
        ("", None),
    ],
)
def test_parse_market_value(raw: object, expected: int | None) -> None:
    assert parse_market_value(raw) == expected


@pytest.mark.parametrize("raw", ["about 5m", "€m", -5, True])
def test_parse_market_value_rejects_garbage(raw: object) -> None:
    with pytest.raises(DataValidationError):
        parse_market_value(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-06-10", date(2026, 6, 10)),
        ("2026-06-10T08:00:00", date(2026, 6, 10)),
        ("Jun 10, 2026", date(2026, 6, 10)),
        ("10.06.2026", date(2026, 6, 10)),
        (date(2026, 6, 10), date(2026, 6, 10)),
        (None, None),
        ("-", None),
    ],
)
def test_parse_tm_date(raw: object, expected: date | None) -> None:
    assert parse_tm_date(raw) == expected


def test_parse_tm_date_rejects_unknown_format() -> None:
    with pytest.raises(DataValidationError):
        parse_tm_date("June the tenth")


def test_normalise_name_and_pick_club() -> None:
    assert normalise_name("  Brighton &  Hove Albion ") == "brighton and hove albion"
    assert normalise_name("Atlético") == "atletico"
    results = [
        TmSearchResult(id="1", name="Synthetic Rovers U21"),
        TmSearchResult(id="2", name="Synthetic Rovers"),
    ]
    hit = pick_club(results, ["Rovers", "Synthetic Rovers"])
    assert hit is not None and hit.id == "2"
    assert pick_club(results, ["Nobody FC"]) is None


def test_parse_rows_with_tm_as_of_date(tmp_path: Path) -> None:
    adapter = TransfermarktAdapter(BASE, CLUBS)
    df = adapter.parse(_snapshots(tmp_path, _payloads())).set_index("tm_player_id")
    alex = df.loc["880011"]
    assert alex["value_eur"] == 32_000_000
    # As-of = latest valuation history point, not the fetch time.
    assert alex["tm_last_updated"] == date(2026, 6, 10)
    assert alex["birth_date"] == date(1998, 3, 14)
    assert alex["contract_expiry"] == date(2028, 6, 30)
    assert alex["tm_position"] == "Centre-Back"
    assert alex["tm_club_id"] == "99001"
    assert alex["tm_club_name"] == "Synthetic Rovers"
    assert bool(alex["is_stale"]) is False
    assert alex["source"] == "transfermarkt"


def test_missing_value_and_dates_stay_null(tmp_path: Path) -> None:
    adapter = TransfermarktAdapter(BASE, CLUBS)
    df = adapter.parse(_snapshots(tmp_path, _payloads())).set_index("tm_player_id")
    cy = df.loc["880013"]
    assert pd.isna(cy["value_eur"])
    assert pd.isna(cy["tm_last_updated"])
    assert pd.isna(cy["birth_date"])
    assert pd.isna(cy["contract_expiry"])


def test_value_without_history_has_no_receipt(tmp_path: Path) -> None:
    payloads = _payloads()
    mv = payloads[market_value_name("880011")]
    assert isinstance(mv, dict)
    mv["marketValueHistory"] = []
    df = TransfermarktAdapter(BASE, CLUBS).parse(_snapshots(tmp_path, payloads))
    alex = df.set_index("tm_player_id").loc["880011"]
    assert pd.isna(alex["value_eur"]) and pd.isna(alex["tm_last_updated"])


def test_schema_changed_fails_loudly(tmp_path: Path) -> None:
    payloads = _payloads()
    squad = payloads[club_players_name("99001")]
    assert isinstance(squad, dict)
    squad["squad"] = squad.pop("players")
    with pytest.raises(DataValidationError, match="schema changed"):
        TransfermarktAdapter(BASE, CLUBS).parse(_snapshots(tmp_path, payloads))


def test_fetch_resolves_club_by_search_and_skips_unmatched(tmp_path: Path) -> None:
    payloads = _payloads()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        if path.startswith("/clubs/search/"):
            if "Synthetic Rovers" in path:
                body = payloads[club_search_name("Synthetic Rovers")]
            else:
                body = {"query": "x", "results": [{"id": "5", "name": "Somebody Else FC"}]}
        elif path == "/clubs/99001/players":
            body = payloads[club_players_name("99001")]
        else:
            player_id = path.split("/")[2]
            body = payloads[market_value_name(player_id)]
        return httpx.Response(200, content=json.dumps(body).encode())

    cfg = load_config(PROJECT_ROOT / "config").settings.ingest
    adapter = TransfermarktAdapter(BASE, {**CLUBS, "Missing Town": []})
    with PoliteClient(
        "transfermarkt",
        cfg,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1e9, 1e9),
    ) as client:
        snaps = adapter.fetch(client, SnapshotStore(tmp_path))
    assert adapter.unmatched_clubs == ["Missing Town"]
    assert "/clubs/99009/players" not in requested  # U21 side never fetched
    assert len(snaps) == 5  # 2 searches + 1 squad + 2 market values
    assert len(adapter.parse(snaps)) == 2
