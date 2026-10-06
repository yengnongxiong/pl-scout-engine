"""pandera schemas for staged (silver) tables and a validation report (PRD §10, §14).

Each adapter output is validated before it reaches the warehouse. A failure stops
``scout build`` unless ``--allow-invalid`` is passed explicitly, and that override is
logged (CLAUDE.md rule 12). Checks encode data-integrity rules: provenance columns are
never null (rule 3), rates and xG are non-negative, possession is a share, and natural
keys are unique.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from scout.config import ValidationConfig
from scout.errors import DataValidationError

logger = logging.getLogger(__name__)


def _provenance() -> dict[str, pa.Column]:
    return {
        "source": pa.Column(str, nullable=False),
        "fetched_at": pa.Column(nullable=False),
    }


def _nonneg(dtype: type = float, *, required: bool = True) -> pa.Column:
    return pa.Column(dtype, pa.Check.ge(0), nullable=True, coerce=True, required=required)


def build_schemas(cfg: ValidationConfig) -> dict[str, pa.DataFrameSchema]:
    """Schemas keyed by staged table name."""
    minutes = pa.Column(
        float, pa.Check.in_range(0, cfg.max_match_minutes), nullable=True, coerce=True
    )
    share = pa.Column(float, pa.Check.in_range(0.0, 1.0), nullable=True, coerce=True)
    return {
        "fpl_player_match": pa.DataFrameSchema(
            {
                "fpl_code": pa.Column(int, nullable=False, coerce=True),
                "fpl_fixture_code": pa.Column(int, nullable=False, coerce=True),
                "team_fpl_code": pa.Column(int, nullable=False, coerce=True),
                "minutes": minutes,
                "goals": _nonneg(),
                "assists": _nonneg(),
                "xg": _nonneg(),
                "xa": _nonneg(),
                "xgc_on_pitch": _nonneg(),
                "tackles": _nonneg(),
                "cbi": _nonneg(),
                "recoveries": _nonneg(),
                "yellow_cards": _nonneg(),
                "red_cards": _nonneg(),
                # Goalkeeping columns (S2) are optional: older payloads may lack them.
                "saves": _nonneg(required=False),
                "goals_conceded": _nonneg(required=False),
                "penalties_saved": _nonneg(required=False),
                **_provenance(),
            },
            unique=["fpl_code", "fpl_fixture_code"],
        ),
        "vaastav_player_match": pa.DataFrameSchema(
            {
                "fpl_code": pa.Column(int, nullable=False, coerce=True),
                "season_id": pa.Column(str, nullable=False),
                "fpl_fixture_id": pa.Column(int, nullable=False, coerce=True),
                "opponent_fpl_code": pa.Column(int, nullable=False, coerce=True),
                "minutes": minutes,
                "goals": _nonneg(),
                "assists": _nonneg(),
                "xg": _nonneg(),
                "xa": _nonneg(),
                "tackles": _nonneg(),
                "cbi": _nonneg(),
                "recoveries": _nonneg(),
                **_provenance(),
            },
            unique=["fpl_code", "season_id", "fpl_fixture_id"],
        ),
        "understat_player_match": pa.DataFrameSchema(
            {
                "understat_player_id": pa.Column(int, nullable=False, coerce=True),
                "understat_game_id": pa.Column(int, nullable=False, coerce=True),
                "minutes": minutes,
                "shots": _nonneg(),
                "xg": _nonneg(),
                "npxg": _nonneg(),
                "xa": _nonneg(),
                "xg_chain": _nonneg(),
                "xg_buildup": _nonneg(),
                "key_passes": _nonneg(),
                **_provenance(),
            },
            unique=["understat_player_id", "understat_game_id"],
        ),
        "understat_team_match": pa.DataFrameSchema(
            {
                "understat_team_id": pa.Column(int, nullable=False, coerce=True),
                "understat_game_id": pa.Column(int, nullable=False, coerce=True),
                "xg": _nonneg(),
                "xga": _nonneg(),
                "ppda": _nonneg(),
                "ppda_allowed": _nonneg(),
                "deep": _nonneg(),
                "deep_allowed": _nonneg(),
                **_provenance(),
            },
            unique=["understat_team_id", "understat_game_id"],
        ),
        "fotmob_possession": pa.DataFrameSchema(
            {
                "game": pa.Column(str, nullable=False),
                "team_name": pa.Column(str, nullable=False),
                "possession_share": share,
                "opp_possession_share": share,
                **_provenance(),
            },
            unique=["game", "team_name"],
        ),
        "tm_market_value": pa.DataFrameSchema(
            {
                "tm_player_id": pa.Column(str, nullable=False),
                "value_eur": _nonneg(float),
                "tm_last_updated": pa.Column(nullable=True),
                **_provenance(),
            },
            # A value must carry Transfermarkt's own as-of date (CLAUDE.md rule 3).
            checks=pa.Check(
                lambda df: df["value_eur"].isna() | df["tm_last_updated"].notna(),
                name="value_eur_requires_tm_last_updated",
                error="value_eur without tm_last_updated",
            ),
        ),
    }


@dataclass
class TableIssue:
    """One failed check on one table."""

    table: str
    check: str
    column: str | None
    failures: int
    examples: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Outcome of validating every staged table."""

    issues: list[TableIssue] = field(default_factory=list)
    tables_checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no check failed."""
        return not self.issues

    def summary(self) -> str:
        """Human-readable one line per issue."""
        if self.ok:
            return f"validation ok ({len(self.tables_checked)} tables)"
        return "\n".join(
            f"{i.table}.{i.column or '*'}: {i.check} failed for {i.failures} row(s)"
            f"{' e.g. ' + ', '.join(i.examples) if i.examples else ''}"
            for i in self.issues
        )


def validate_tables(frames: Mapping[str, pd.DataFrame], cfg: ValidationConfig) -> ValidationReport:
    """Validate each frame that has a schema; unknown table names are an error."""
    schemas = build_schemas(cfg)
    report = ValidationReport()
    for table, frame in frames.items():
        schema = schemas.get(table)
        if schema is None:
            raise DataValidationError(f"no validation schema for staged table {table!r}")
        report.tables_checked.append(table)
        try:
            schema.validate(frame, lazy=True)
        except SchemaErrors as exc:
            cases = exc.failure_cases
            pairs = cases[["column", "check"]].drop_duplicates()
            for column, check in pairs.itertuples(index=False):
                column_missing = bool(pd.isna(column))
                same_column = (
                    cases["column"].isna() if column_missing else cases["column"] == column
                )
                group = cases[same_column & (cases["check"] == check)]
                report.issues.append(
                    TableIssue(
                        table=table,
                        check=str(check),
                        column=None if column_missing else str(column),
                        failures=len(group),
                        examples=[str(v) for v in group["failure_case"].head(3)],
                    )
                )
    return report


def enforce(report: ValidationReport, *, allow_invalid: bool) -> None:
    """Stop the build on validation failures unless explicitly overridden (rule 12).

    Raises:
        DataValidationError: If the report has issues and ``allow_invalid`` is False.
    """
    if report.ok:
        return
    if allow_invalid:
        logger.warning("building despite validation failures (--allow-invalid)")
        logger.warning(report.summary())
        return
    raise DataValidationError(
        "validation failed; fix the data or pass --allow-invalid",
        details={"issues": [i.__dict__ for i in report.issues]},
    )
