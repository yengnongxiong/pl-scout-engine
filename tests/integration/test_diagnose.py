from pathlib import Path

import pytest
from typer.testing import CliRunner

from scout import cli
from scout.config import PROJECT_ROOT, AppConfig, Settings, load_config
from scout.db.session import make_engine
from scout.engines.diagnosis import diagnose, find_team
from scout.errors import NotFoundError
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


def test_cli_diagnose(built: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: built)
    monkeypatch.setattr(cli, "get_config", _config)
    ok = CliRunner().invoke(cli.app, ["diagnose", "Synthetic Rovers", "--top", "2"])
    assert ok.exit_code == 0, ok.output
    assert "Synthetic Rovers vs top6" in ok.output
    assert "1. " in ok.output and "evidence rows" in ok.output
    bad = CliRunner().invoke(cli.app, ["diagnose", "Nowhere United"])
    assert bad.exit_code == 1
    wrong = CliRunner().invoke(cli.app, ["diagnose", "Synthetic Rovers", "--benchmark", "top9"])
    assert wrong.exit_code == 2
