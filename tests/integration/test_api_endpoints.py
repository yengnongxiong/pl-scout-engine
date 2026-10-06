"""Every API endpoint against the fixture warehouse (milestone M7)."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from scout.api.main import create_app
from scout.config import Settings
from scout.pipeline import build_all
from tests.integration.test_build import _seed
from tests.integration.test_diagnose import _config


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    tmp = tmp_path_factory.mktemp("api")
    settings = Settings(data_dir=tmp / "data", database_url=f"sqlite:///{tmp / 'w.db'}")
    _seed(settings.data_dir)
    build_all(settings, _config())
    return settings


@pytest.fixture
def client(built: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(built, _config())) as c:
        yield c


def _ids(client: TestClient) -> dict[str, int]:
    teams = {t["name"]: t["team_id"] for t in client.get("/teams").json()}
    players = {
        h["name"]: h["player_id"]
        for q in ("Bo", "Alex", "Cy")
        for h in client.get("/players/search", params={"q": q}).json()
    }
    return {**teams, **players}


def _error(resp: httpx.Response, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"} and body["error"]["code"] == code


def test_health_reports_the_build(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["warehouse_version"] is not None


def test_teams_and_search(client: TestClient) -> None:
    teams = client.get("/teams").json()
    assert [t["name"] for t in teams] == sorted(t["name"] for t in teams)
    assert {"Synthetic Rovers", "Fixture Town"} <= {t["name"] for t in teams}
    hits = client.get("/teams/search", params={"q": "rov"}).json()
    assert hits[0]["name"] == "Synthetic Rovers" and hits[0]["kind"] == "prefix"
    fuzzy = client.get("/teams/search", params={"q": "Fixtur Twn"}).json()
    assert fuzzy and fuzzy[0]["name"] == "Fixture Town" and fuzzy[0]["kind"] == "fuzzy"
    assert client.get("/teams/search", params={"q": "zzzzzz"}).json() == []
    _error(client.get("/teams/search"), 422, "invalid_request")


def test_diagnosis(client: TestClient) -> None:
    ids = _ids(client)
    rovers = ids["Synthetic Rovers"]
    body = client.get(f"/teams/{rovers}/diagnosis").json()
    assert body["team_name"] == "Synthetic Rovers" and body["benchmark"] == "top6"
    assert body["current_season"] == "2026-27"
    assert [t["name"] for t in body["benchmark_teams"]] == ["Fixture Town"]
    assert [n["rank"] for n in body["needs"]] == list(range(1, len(body["needs"]) + 1))
    cb = next(n for n in body["needs"] if n["position_group"] == "CB")
    assert cb["need_id"] == f"{rovers}-CB"
    assert all(e["source"] and e["as_of"] and e["label"] for e in cb["evidence"])
    assert all(t["source"] == "understat" for t in body["team_needs"])
    league = client.get(f"/teams/{rovers}/diagnosis", params={"benchmark": "league"}).json()
    assert league["benchmark"] == "league"
    current = client.get(f"/teams/{rovers}/diagnosis", params={"season_mode": "current"})
    assert current.json()["season_mode"] == "current"
    town = ids["Fixture Town"]
    custom = client.get(
        f"/teams/{rovers}/diagnosis", params={"benchmark": "custom", "custom": [town]}
    )
    assert [t["team_id"] for t in custom.json()["benchmark_teams"]] == [town]
    _error(client.get("/teams/999/diagnosis"), 404, "not_found")
    _error(client.get(f"/teams/{rovers}/diagnosis", params={"benchmark": "top9"}), 422,
           "invalid_request")  # fmt: skip
    _error(client.get(f"/teams/{rovers}/diagnosis", params={"benchmark": "custom"}), 422,
           "invalid_request")  # fmt: skip
    _error(
        client.get(f"/teams/{rovers}/diagnosis", params={"benchmark": "custom", "custom": [999]}),
        422,
        "invalid_request",
    )


def test_recommendations(client: TestClient) -> None:
    ids = _ids(client)
    rovers, town = ids["Synthetic Rovers"], ids["Fixture Town"]
    body = client.get(f"/teams/{rovers}/recommendations", params={"need_id": f"{rovers}-ST"}).json()
    assert body["position_group"] == "ST" and body["incumbent"] is None
    [bo] = body["candidates"]
    assert (bo["player_name"], bo["team_name"], bo["gate"]) == ("Bo Fakeson", "Fixture Town",
                                                              "no_incumbent")  # fmt: skip
    assert bo["market_value"] is None and bo["implied_value"] is None
    assert bo["fit"]["total"] is not None and set(bo["fit"]["components"]) >= {"need_fill"}
    filtered = client.get(
        f"/teams/{rovers}/recommendations",
        params={"position_group": "ST", "exclude_team_ids": [town], "max_value_eur": 1},
    ).json()
    assert filtered["candidates"] == [] and filtered["excluded"] == {"excluded club": 1}
    default = client.get(f"/teams/{rovers}/recommendations").json()
    assert default["need_id"].startswith(f"{rovers}-")
    for params in ({"need_id": "999-ST"}, {"need_id": f"{rovers}-ST", "position_group": "CB"},
                   {"min_age": 30, "max_age": 20}, {"limit": 0}):  # fmt: skip
        _error(client.get(f"/teams/{rovers}/recommendations", params=params), 422,
               "invalid_request")  # fmt: skip
    _error(client.get(f"/teams/{rovers}/recommendations", params={"position_group": "GK"}),
           404, "not_found")  # fmt: skip


def test_players(client: TestClient) -> None:
    ids = _ids(client)
    bo, alex = ids["Bo Fakeson"], ids["Alex Testman"]
    hits = client.get("/players/search", params={"q": "fakes"}).json()
    assert hits[0]["name"] == "Bo Fakeson" and hits[0]["team_name"] == "Fixture Town"
    profile = client.get(f"/players/{alex}").json()
    assert profile["player_name"] == "Alex Testman" and profile["position_group"] == "CB"
    assert profile["market_value"]["value_eur"] > 0 and profile["market_value"]["tm_last_updated"]
    assert all(k["source"] and k["as_of"] for k in profile["kpis"])
    assert profile["fit"] is None
    _error(client.get("/players/999999"), 404, "not_found")
    similar = client.get(f"/players/{bo}/similar")
    _error(similar, 404, "not_found")  # the fixture's only striker has no peers
    _error(client.get("/players/999999/similar"), 404, "not_found")
    report = client.get(f"/players/{bo}/report", params={"team_id": ids["Synthetic Rovers"]})
    body = report.json()
    assert body["report"]["engine"] == "template" and body["report"]["violations"] == []
    assert body["report"]["text"].startswith("SCOUTING REPORT: Bo Fakeson")
    assert body["facts"]["fit"]["team_name"] == "Synthetic Rovers"
    _error(client.get(f"/players/{bo}/report", params={"team_id": 999}), 404, "not_found")
    _error(client.get(f"/players/{bo}/report", params={"benchmark": "custom"}), 422,
           "invalid_request")  # fmt: skip


def test_compare(client: TestClient) -> None:
    ids = _ids(client)
    bo, alex, rovers = ids["Bo Fakeson"], ids["Alex Testman"], ids["Synthetic Rovers"]
    body = client.get("/compare", params={"a": bo, "b": alex, "team_id": rovers}).json()
    assert (body["a"]["player_name"], body["b"]["player_name"]) == ("Bo Fakeson", "Alex Testman")
    assert body["team"]["name"] == "Synthetic Rovers"
    kpis = [r["kpi"] for r in body["rows"]]
    assert len(kpis) == len(set(kpis)) and "npxg_p90" in kpis and "cbi_padj_p90" in kpis
    shared = [r for r in body["rows"] if r["a"] and r["b"]]
    for row in shared:
        assert row["delta"] == pytest.approx(row["a"]["percentile"] - row["b"]["percentile"])
    _error(client.get("/compare", params={"a": bo, "b": bo}), 422, "invalid_request")
    _error(client.get("/compare", params={"a": bo, "b": alex, "team_id": 999}), 404, "not_found")
    _error(client.get("/compare", params={"a": bo}), 422, "invalid_request")


def test_meta(client: TestClient) -> None:
    fresh = client.get("/meta/freshness").json()
    assert {s["source"] for s in fresh["sources"]} >= {"fpl", "understat"}
    assert fresh["warehouse_version"] is not None
    method = client.get("/meta/methodology").json()
    assert any(k["is_proxy"] and k["proxy_for"] for k in method["kpis"])
    assert sum(method["fit_weights"].values()) == pytest.approx(1.0)
    assert {m["name"] for m in method["models"]} == {"role archetypes", "value model"}
    assert all(m["rows"] == 0 and m["trained_at"] is None for m in method["models"])
    assert method["limitations"] and method["value_model_caveat"]


def test_hot_endpoints_are_cached(built: Settings) -> None:
    app = create_app(built, _config())
    state = app.state.scout
    with TestClient(app) as c:
        rovers = next(
            t["team_id"] for t in c.get("/teams").json() if t["name"] == "Synthetic Rovers"
        )
        first = c.get(f"/teams/{rovers}/diagnosis").json()
        hits = state.cache.hits
        assert c.get(f"/teams/{rovers}/diagnosis").json() == first
        assert state.cache.hits > hits


def test_unknown_routes_use_the_error_schema(client: TestClient) -> None:
    _error(client.get("/nope"), 404, "not_found")


def test_missing_warehouse_is_a_503(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'none.db'}"
    )
    with TestClient(create_app(settings, _config())) as c:
        assert c.get("/health").json()["warehouse_version"] is None
        for path in ("/teams", "/teams/1/diagnosis", "/players/search?q=a", "/meta/methodology"):
            _error(c.get(path), 503, "warehouse_not_ready")


def test_similar_players_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from scout.api.routers import players
    from scout.ml.similarity import SimilarPlayer

    ids = _ids(client)
    bo, alex = ids["Bo Fakeson"], ids["Alex Testman"]
    calls: list[int] = []

    def fake(_engine: object, player_id: int, _config: object, *, k: int, season_mode: str):
        calls.append(k)
        return [SimilarPlayer(alex, 0.5), SimilarPlayer(424242, 0.1)]

    monkeypatch.setattr(players, "find_similar", fake)
    body = client.get(f"/players/{bo}/similar", params={"k": 3}).json()
    assert calls == [3] and body["position_group"] == "ST"
    first, unknown = body["results"]
    assert (first["player_name"], first["team_name"], first["similarity"]) == (
        "Alex Testman",
        "Synthetic Rovers",
        0.5,
    )
    assert unknown["team_id"] is None and unknown["player_name"] == "424242"


def test_backtest_endpoint(client: TestClient) -> None:
    body = client.get("/meta/backtest").json()
    assert (body["as_of_season"], body["signing_season"], body["top_n"]) == (
        "2025-26",
        "2026-27",
        3,
    )
    assert body["evaluated"] == 0 and body["precision"] is None
    assert body["skipped"] == {"no arrivals yet": 2}
    assert {c["team_name"] for c in body["clubs"]} == {"Synthetic Rovers", "Fixture Town"}
    assert body["caveat"].startswith("Exploratory")
