from typer.testing import CliRunner

from scout import __version__
from scout.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config-check" in result.output
    assert "version" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_config_check_passes_on_committed_config() -> None:
    result = runner.invoke(app, ["config-check"])
    assert result.exit_code == 0, result.output
    assert "Config OK" in result.output
