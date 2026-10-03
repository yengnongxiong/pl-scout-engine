from datetime import UTC, date, datetime

import pandas as pd
import pytest

from scout.config import PROJECT_ROOT, load_config
from scout.errors import DataValidationError
from scout.transform.validate import enforce, validate_tables

CFG = load_config(PROJECT_ROOT / "config").settings.validation
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def fpl_rows(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "fpl_code": 500011,
        "fpl_fixture_code": 7000101,
        "team_fpl_code": 9001,
        "minutes": 90,
        "goals": 0,
        "assists": 1,
        "xg": 0.05,
        "xa": 0.31,
        "xgc_on_pitch": 1.2,
        "tackles": 3,
        "cbi": 7,
        "recoveries": 5,
        "yellow_cards": 1,
        "red_cards": 0,
        "source": "fpl",
        "fetched_at": NOW,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_valid_frame_passes() -> None:
    report = validate_tables({"fpl_player_match": fpl_rows()}, CFG)
    assert report.ok
    assert report.tables_checked == ["fpl_player_match"]
    assert "validation ok" in report.summary()
    enforce(report, allow_invalid=False)


def test_missing_values_are_allowed_but_negative_are_not() -> None:
    assert validate_tables({"fpl_player_match": fpl_rows(xg=None)}, CFG).ok
    report = validate_tables({"fpl_player_match": fpl_rows(xg=-0.1)}, CFG)
    assert not report.ok
    assert report.issues[0].column == "xg"
    assert report.issues[0].failures == 1


def test_minutes_above_threshold_fail() -> None:
    report = validate_tables({"fpl_player_match": fpl_rows(minutes=CFG.max_match_minutes + 1)}, CFG)
    assert [i.column for i in report.issues] == ["minutes"]


def test_provenance_required() -> None:
    report = validate_tables({"fpl_player_match": fpl_rows(source=None)}, CFG)
    assert any(i.column == "source" for i in report.issues)


def test_duplicate_natural_key_fails() -> None:
    frame = pd.concat([fpl_rows(), fpl_rows()], ignore_index=True)
    report = validate_tables({"fpl_player_match": frame}, CFG)
    assert not report.ok


def test_possession_must_be_a_share() -> None:
    frame = pd.DataFrame(
        [
            {
                "game": "g",
                "team_name": "A",
                "possession_share": 58.0,
                "opp_possession_share": 0.42,
                "source": "fotmob",
                "fetched_at": NOW,
            }
        ]
    )
    report = validate_tables({"fotmob_possession": frame}, CFG)
    assert [i.column for i in report.issues] == ["possession_share"]


def test_market_value_needs_tm_as_of_date() -> None:
    def frame(last_updated: date | None, value: float | None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "tm_player_id": "880011",
                    "value_eur": value,
                    "tm_last_updated": last_updated,
                    "source": "transfermarkt",
                    "fetched_at": NOW,
                }
            ]
        )

    assert validate_tables({"tm_market_value": frame(date(2026, 6, 10), 3.2e7)}, CFG).ok
    assert validate_tables({"tm_market_value": frame(None, None)}, CFG).ok
    report = validate_tables({"tm_market_value": frame(None, 3.2e7)}, CFG)
    assert not report.ok
    assert "tm_last_updated" in report.summary()


def test_enforce_stops_build_unless_overridden(caplog: pytest.LogCaptureFixture) -> None:
    report = validate_tables({"fpl_player_match": fpl_rows(xg=-1.0)}, CFG)
    with pytest.raises(DataValidationError, match="--allow-invalid"):
        enforce(report, allow_invalid=False)
    with caplog.at_level("WARNING"):
        enforce(report, allow_invalid=True)
    assert "allow-invalid" in caplog.text


def test_unknown_table_rejected() -> None:
    with pytest.raises(DataValidationError, match="no validation schema"):
        validate_tables({"mystery": pd.DataFrame()}, CFG)
