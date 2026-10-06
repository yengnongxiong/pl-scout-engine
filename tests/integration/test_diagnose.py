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


def test_cli_train_reports_models_it_could_not_train(
    built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    out = tmp_path / "EVALUATION.md"
    result = CliRunner().invoke(cli.app, ["train", "--out", str(out)])
    assert result.exit_code == 0, result.output
    # Three fixture players and one unlabelled past season: nothing to train on.
    assert "Role archetypes: not trained" in result.output
    assert "Value model: not trained (no labelled past player-seasons" in result.output
    assert f"Wrote {out}" in result.output
    text = out.read_text()
    assert text.startswith("# Evaluation") and "Not available" in text
    assert (built.data_dir / "models").is_dir()


def test_assess_player_scores_one_player_without_filters(built: Settings) -> None:
    from scout.db.queries import player_profiles
    from scout.engines.recommend import assess_player

    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    town = find_team(engine, "Fixture Town", config.team_aliases.aliases)
    ids = {
        str(n): int(p) for n, p in player_profiles(engine)[["canonical_name", "player_id"]].values
    }
    shortlist = recommend(engine, rovers.team_id, config, position_group="ST")
    bo = assess_player(engine, rovers.team_id, ids["Bo Fakeson"], config)
    own = assess_player(engine, rovers.team_id, ids["Alex Testman"], config)
    with pytest.raises(NotFoundError):
        assess_player(engine, rovers.team_id, 999_999, config)
    engine.dispose()
    # Same numbers as the shortlist entry, for the player's own position group.
    assert bo.context.position_group == "ST" and not bo.same_club
    assert bo.candidate.fit == shortlist.candidates[0].fit
    assert bo.candidate.team_id == town.team_id
    # A player at the club itself can still be assessed (the report says so).
    assert own.same_club and own.context.position_group == "CB"
    assert own.context.incumbent is not None
    assert own.context.incumbent.player_name == "Alex Testman"


def test_fact_sheet_from_the_warehouse_has_receipts(built: Settings) -> None:
    from datetime import date

    from scout.db.queries import player_profiles
    from scout.reports.facts import build_fact_sheet
    from scout.reports.generate import generate_report, template_vocabulary
    from scout.reports.grounding import validate
    from scout.reports.render import render_template_report

    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    ids = {
        str(n): int(p) for n, p in player_profiles(engine)[["canonical_name", "player_id"]].values
    }
    bo = build_fact_sheet(
        engine, ids["Bo Fakeson"], config, team_id=rovers.team_id, as_of=date(2026, 10, 1)
    )
    alex = build_fact_sheet(engine, ids["Alex Testman"], config, as_of=date(2026, 10, 1))
    with pytest.raises(NotFoundError):
        build_fact_sheet(engine, 999_999, config)
    with pytest.raises(NotFoundError):
        build_fact_sheet(engine, ids["Bo Fakeson"], config, team_id=999_999)
    engine.dispose()
    assert (bo.team_name, bo.position_group, bo.current_season) == ("Fixture Town", "ST", "2026-27")
    assert bo.fit is not None and bo.fit.team_name == "Synthetic Rovers" and not bo.fit.same_club
    assert bo.fit.gate == "no_incumbent" and bo.fit.incumbent is None
    assert bo.market_value is None and bo.age is None  # missing stays missing
    kinds = {c.kind for c in bo.caveats}
    assert {"small_sample", "no_market_value", "proxy_metric", "no_comparables"} <= kinds
    assert all(k.source and k.as_of for k in bo.kpis)
    assert {r.source for r in bo.sources} >= {"fpl", "understat"}
    # Alex has last season's minutes in the blend and a Transfermarkt value with its date.
    assert alex.previous_season == "2025-26" and alex.fit is None
    assert alex.market_value is not None and alex.market_value.source == "transfermarkt"
    assert "no_previous_season" not in {c.kind for c in alex.caveats}
    for sheet in (bo, alex):
        text = render_template_report(sheet, config)
        assert validate(text, sheet, reference=template_vocabulary()).ok
        assert generate_report(sheet, built, config).engine == "template"


def test_cli_report(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    ok = CliRunner().invoke(cli.app, ["report", "Bo Fakeson", "--team", "Synthetic Rovers"])
    assert ok.exit_code == 0, ok.output
    assert ok.output.startswith("SCOUTING REPORT: Bo Fakeson")
    assert "WHY BO FAKESON FITS SYNTHETIC ROVERS" in ok.output
    facts = CliRunner().invoke(cli.app, ["report", "Bo Fakeson", "--facts"])
    assert facts.exit_code == 0 and '"player_name": "Bo Fakeson"' in facts.output
    missing = CliRunner().invoke(cli.app, ["report", "Nobody Atall"])
    assert missing.exit_code == 1 and "0 players match" in missing.output
    unknown = CliRunner().invoke(cli.app, ["report", "999999"])
    assert unknown.exit_code == 1 and "Report failed" in unknown.output
    wrong = CliRunner().invoke(cli.app, ["report", "1", "--benchmark", "top9"])
    assert wrong.exit_code == 2


def test_backtest_compares_last_seasons_needs_with_arrivals(
    built: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from scout.db.models import DimMatch, DimPlayer, FactPlayerMatch
    from scout.db.session import make_session_factory
    from scout.engines import backtest
    from scout.engines.diagnosis import GroupAssessment

    engine = make_engine(built.database_url)
    config = _config()
    rovers = find_team(engine, "Synthetic Rovers", config.team_aliases.aliases)
    # A new striker plays for Rovers this season: a summer arrival.
    with make_session_factory(engine).begin() as session:
        match = session.scalars(select(DimMatch).where(DimMatch.season_id == "2026-27")).first()
        assert match is not None
        newcomer = DimPlayer(canonical_name="Nia Newcomer", position_group="ST")
        session.add(newcomer)
        session.flush()
        session.add(
            FactPlayerMatch(
                player_id=newcomer.player_id, match_id=match.match_id, team_id=rovers.team_id,
                minutes=75, source="fpl", fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )  # fmt: skip

    def needs(club: int, *_args: object) -> list[GroupAssessment]:
        # Stub the season-end assessment so a club has shortfalls to compare.
        return [GroupAssessment("ST", 9.0), GroupAssessment("CB", 4.0), GroupAssessment("W", 0.0)]

    monkeypatch.setattr(backtest, "assess_groups", needs)
    result = backtest.run_backtest(engine, config)
    engine.dispose()
    assert (result.as_of_season, result.signing_season, result.benchmark) == (
        "2025-26",
        "2026-27",
        "top6",
    )
    assert result.history_as_of is not None and result.arrivals_as_of is not None
    by_name = {c.team_name: c for c in result.clubs}
    rov = by_name["Synthetic Rovers"]
    assert [p.position_group for p in rov.predicted] == ["ST", "CB"]  # severity 0 dropped
    assert [a.player_name for a in rov.arrivals] == ["Nia Newcomer"]
    assert rov.hits == ["ST"] and rov.precision == pytest.approx(0.5)
    assert rov.baseline_groups == [] and rov.baseline_precision is None
    assert rov.random_precision == pytest.approx(1 / 7)
    assert result.evaluated == 1 and result.precision == pytest.approx(0.5)
    assert result.hit_rate == 1.0
    assert result.skipped == {"no arrivals yet": 1}


def test_backtest_needs_last_seasons_history(tmp_path: Path) -> None:
    from scout.engines.backtest import run_backtest
    from scout.pipeline import build_all

    settings = Settings(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'w.db'}")
    _seed(settings.data_dir)
    for path in (settings.data_dir / "raw" / "vaastav").rglob("*"):
        if path.name.startswith("2025-26"):
            path.unlink()
    build_all(settings, _config())
    engine = make_engine(settings.database_url)
    with pytest.raises(NotFoundError, match="no FPL history for 2025-26"):
        run_backtest(engine, _config())
    engine.dispose()


def test_cli_backtest(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    ok = CliRunner().invoke(cli.app, ["backtest"])
    assert ok.exit_code == 0, ok.output
    assert "Needs at the end of 2025-26" in ok.output and "precision@3 Not available" in ok.output
    assert "Synthetic Rovers: needs none; arrivals none yet" in ok.output
    assert "Skipped: no arrivals yet 2" in ok.output
