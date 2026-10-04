from pathlib import Path

import pytest
from typer.testing import CliRunner

from scout import cli
from scout.config import PROJECT_ROOT, AppConfig, Settings, load_config
from scout.db.session import make_engine
from scout.engines.diagnosis import diagnose, find_team
from scout.engines.recommend import Filters, recommend
from scout.errors import NotFoundError
from scout.ml.similarity import find_similar
from scout.pipeline import build_all
from tests.integration.test_build import _seed

BASE = load_config(PROJECT_ROOT / "config")


def _config() -> AppConfig:
    # The fixture squads are tiny, so rank everyone (threshold 0) to get percentiles.
    method = BASE.settings.methodology.model_copy(update={"percentile_min_minutes": 0})
    settings = BASE.settings.model_copy(update={"methodology": method})
    return BASE.model_copy(update={"settings": settings})


@pytest.fixture
def built(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    build_all(settings, _config())
    return settings


def test_last_season_table_counts_every_scored_match(built: Settings) -> None:
    from scout.db.queries import standings

    engine = make_engine(built.database_url)
    table = standings(engine, "2025-26")
    engine.dispose()
    # Both 2025-26 games have scores, including the one vaastav created first.
    assert sorted(table["played"]) == [2, 2]


def test_find_team_by_name_and_id(built: Settings) -> None:
    engine = make_engine(built.database_url)
    rovers = find_team(engine, "Synthetic Rovers", BASE.team_aliases.aliases)
    assert find_team(engine, str(rovers.team_id), BASE.team_aliases.aliases).name == rovers.name
    with pytest.raises(NotFoundError):
        find_team(engine, "Nowhere United", BASE.team_aliases.aliases)
    engine.dispose()


def test_diagnosis_ranks_every_group_with_receipts(built: Settings) -> None:
    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    town = find_team(engine, "Fixture Town", config.team_aliases.aliases)
    result = diagnose(engine, rovers.team_id, config)
    engine.dispose()
    assert result.benchmark == "top6"
    assert result.benchmark_team_ids == [town.team_id]  # last season's table minus Rovers
    assert [n.rank for n in result.needs] == list(range(1, len(config.kpis.position_groups) + 1))
    severities = [n.severity for n in result.needs]
    assert severities == sorted(severities, reverse=True)
    cb = next(n for n in result.needs if n.position_group == "CB")
    assert cb.evidence, "CB need must carry evidence"
    assert all(e.source and e.as_of for e in cb.evidence)
    assert {e.player_name for e in cb.evidence} == {"Alex Testman"}


def test_team_level_needs_from_last_season(built: Settings) -> None:
    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    blended = diagnose(engine, rovers.team_id, config)
    current = diagnose(engine, rovers.team_id, config, season_mode="current")
    engine.dispose()
    needs = {t.kpi: t for t in blended.team_needs}
    # 2025-26 fixture games: Rovers' xG 0.45 in one game with data vs Town's 0.95 over two
    # (0.475 per 90), so Rovers rank bottom of two; Rovers press harder (PPDA 8.5 vs
    # 11.125), so PPDA is not a need.
    xg = needs["xg_p90"]
    assert (xg.club_value, xg.benchmark_value) == (pytest.approx(0.45), pytest.approx(0.475))
    assert (xg.club_percentile, xg.benchmark_percentile, xg.gap) == (0.0, 100.0, 100.0)
    assert (xg.matches, xg.previous_matches, xg.n_peers) == (0, 1, 2)
    assert needs["xga_p90"].club_value == pytest.approx(0.475)  # (0.95 + 0.00) / 2
    assert "ppda" not in needs
    assert all(t.source == "understat" and t.as_of for t in blended.team_needs)
    for need in blended.needs:
        assert need.team_needs == [
            t for t in blended.team_needs if need.position_group in t.responsible_groups
        ]
    st = next(n for n in blended.needs if n.position_group == "ST")
    assert "xg_p90" in {t.kpi for t in st.team_needs}
    # Current-season mode: the fixtures have no 2026-27 Understat games, so no evidence.
    assert current.team_needs == []


def test_cli_diagnose(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    ok = CliRunner().invoke(cli.app, ["diagnose", "Synthetic Rovers", "--top", "2"])
    assert ok.exit_code == 0, ok.output
    assert "Synthetic Rovers vs top6" in ok.output
    assert "1. " in ok.output and "evidence rows" in ok.output
    assert "Team-level needs" in ok.output and "understat as of" in ok.output
    bad = CliRunner().invoke(cli.app, ["diagnose", "Nowhere United"])
    assert bad.exit_code == 1
    wrong = CliRunner().invoke(cli.app, ["diagnose", "Synthetic Rovers", "--benchmark", "top9"])
    assert wrong.exit_code == 2


def test_recommend_shortlist_with_breakdown_and_receipts(built: Settings) -> None:
    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    town = find_team(engine, "Fixture Town", config.team_aliases.aliases)
    shortlist = recommend(engine, rovers.team_id, config, position_group="ST")
    top_need = recommend(engine, rovers.team_id, config)
    budget = recommend(
        engine, rovers.team_id, config, position_group="ST", filters=Filters(max_value_eur=10)
    )
    no_town = recommend(
        engine,
        rovers.team_id,
        config,
        position_group="ST",
        filters=Filters(exclude_team_ids=(town.team_id,)),
    )
    with pytest.raises(NotFoundError):
        recommend(engine, rovers.team_id, config, position_group="GK")
    engine.dispose()
    assert top_need.position_group == diagnose_top_group(built, rovers.team_id)
    # Rovers have no striker, so there is no incumbent and every candidate clears the gate.
    assert shortlist.incumbent is None
    assert [c.player_name for c in shortlist.candidates] == ["Bo Fakeson"]
    bo = shortlist.candidates[0]
    assert (bo.rank, bo.team_name, bo.gate, bo.fpl_status) == (
        1,
        "Fixture Town",
        "no_incumbent",
        "d",
    )
    assert bo.market_value is None  # no Transfermarkt valuation: "Not available", not 0
    # The FitScore is the weighted sum of the components it used (weights renormalised).
    used = bo.fit.weights_used
    assert sum(used.values()) == pytest.approx(1.0)
    assert bo.fit.total == pytest.approx(
        sum(w * (bo.fit.components[n] or 0) for n, w in used.items())
    )
    # Reliability: doubtful with FPL's 75% chance of playing.
    volume = min(1.0, (bo.effective_minutes or 0) / 2500)
    assert bo.fit.components["reliability"] == pytest.approx(100 * (0.6 * volume + 0.4 * 0.75))
    # Last season's style vectors are mirror images (two clubs, z = +/-1): StyleFit 0.
    assert bo.fit.components["style_fit"] == pytest.approx(0.0)
    assert all(e.source and e.as_of for e in bo.evidence if e.percentile is not None)
    assert budget.candidates == [] and budget.excluded == {"no market value": 1}
    assert no_town.candidates == [] and no_town.excluded == {"excluded club": 1}


def diagnose_top_group(settings: Settings, team_id: int) -> str:
    engine = make_engine(settings.database_url)
    group = diagnose(engine, team_id, _config()).needs[0].position_group
    engine.dispose()
    return group


def test_cli_recommend(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    ok = CliRunner().invoke(cli.app, ["recommend", "Synthetic Rovers", "--need", "ST"])
    assert ok.exit_code == 0, ok.output
    assert "Synthetic Rovers: ST need" in ok.output and "no incumbent" in ok.output
    assert "1. Bo Fakeson (Fixture Town)" in ok.output and "FitScore" in ok.output
    assert "Transfermarkt estimated market value: Not available" in ok.output
    capped = CliRunner().invoke(
        cli.app, ["recommend", "Synthetic Rovers", "--need", "ST", "--max-value", "5"]
    )
    assert capped.exit_code == 0 and "Filtered out: no market value 1" in capped.output
    bad = CliRunner().invoke(cli.app, ["recommend", "Synthetic Rovers", "--need", "GK"])
    assert bad.exit_code == 1


def test_similarity_needs_a_peer_group(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from scout.db.queries import player_profiles

    engine = make_engine(built.database_url)
    ids = {
        str(n): int(p) for n, p in player_profiles(engine)[["canonical_name", "player_id"]].values
    }
    # Bo is the fixture's only striker: no spread to standardise against, so no profile.
    with pytest.raises(NotFoundError, match="complete KPI profile"):
        find_similar(engine, ids["Bo Fakeson"], _config())
    with pytest.raises(NotFoundError, match="no features"):
        find_similar(engine, 999_999, _config())
    engine.dispose()
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    out = CliRunner().invoke(cli.app, ["similar", str(ids["Bo Fakeson"])])
    assert out.exit_code == 1 and "Similarity failed" in out.output
