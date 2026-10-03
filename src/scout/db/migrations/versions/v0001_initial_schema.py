"""Initial gold-layer star schema (PRD §11).

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create every warehouse table."""
    op.create_table(
        "dim_season",
        sa.Column("season_id", sa.String(7), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("season_id", name=op.f("pk_dim_season")),
    )
    op.create_table(
        "dim_team",
        sa.Column("team_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("short_name", sa.String(10), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("fpl_code", sa.Integer(), nullable=True),
        sa.Column("understat_id", sa.Integer(), nullable=True),
        sa.Column("tm_id", sa.String(20), nullable=True),
        sa.PrimaryKeyConstraint("team_id", name=op.f("pk_dim_team")),
        sa.UniqueConstraint("fpl_code", name=op.f("uq_dim_team_fpl_code")),
        sa.UniqueConstraint("understat_id", name=op.f("uq_dim_team_understat_id")),
        sa.UniqueConstraint("tm_id", name=op.f("uq_dim_team_tm_id")),
    )
    op.create_table(
        "dim_player",
        sa.Column("player_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(150), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("fpl_code", sa.Integer(), nullable=True),
        sa.Column("understat_id", sa.Integer(), nullable=True),
        sa.Column("tm_id", sa.String(20), nullable=True),
        sa.Column("detailed_position", sa.String(50), nullable=True),
        sa.Column("position_group", sa.String(3), nullable=True),
        sa.PrimaryKeyConstraint("player_id", name=op.f("pk_dim_player")),
        sa.UniqueConstraint("fpl_code", name=op.f("uq_dim_player_fpl_code")),
        sa.UniqueConstraint("understat_id", name=op.f("uq_dim_player_understat_id")),
        sa.UniqueConstraint("tm_id", name=op.f("uq_dim_player_tm_id")),
    )
    op.create_table(
        "dim_match",
        sa.Column("match_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("season_id", sa.String(7), nullable=False),
        sa.Column("gameweek", sa.Integer(), nullable=True),
        sa.Column("kickoff", TZ, nullable=True),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("fpl_fixture_code", sa.Integer(), nullable=True),
        sa.Column("understat_game_id", sa.Integer(), nullable=True),
        sa.Column("fotmob_game", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["dim_season.season_id"],
            name=op.f("fk_dim_match_season_id_dim_season"),
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"],
            ["dim_team.team_id"],
            name=op.f("fk_dim_match_home_team_id_dim_team"),
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"],
            ["dim_team.team_id"],
            name=op.f("fk_dim_match_away_team_id_dim_team"),
        ),
        sa.PrimaryKeyConstraint("match_id", name=op.f("pk_dim_match")),
        sa.UniqueConstraint("fpl_fixture_code", name=op.f("uq_dim_match_fpl_fixture_code")),
        sa.UniqueConstraint("understat_game_id", name=op.f("uq_dim_match_understat_game_id")),
        sa.UniqueConstraint("fotmob_game", name=op.f("uq_dim_match_fotmob_game")),
    )
    op.create_table(
        "fact_player_match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("started", sa.Boolean(), nullable=True),
        sa.Column("goals", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("xg", sa.Float(), nullable=True),
        sa.Column("npxg", sa.Float(), nullable=True),
        sa.Column("xa", sa.Float(), nullable=True),
        sa.Column("shots", sa.Integer(), nullable=True),
        sa.Column("key_passes", sa.Integer(), nullable=True),
        sa.Column("xg_chain", sa.Float(), nullable=True),
        sa.Column("xg_buildup", sa.Float(), nullable=True),
        sa.Column("tackles", sa.Integer(), nullable=True),
        sa.Column("recoveries", sa.Integer(), nullable=True),
        sa.Column("cbi", sa.Integer(), nullable=True),
        sa.Column("def_contribution", sa.Integer(), nullable=True),
        sa.Column("xgc_on_pitch", sa.Float(), nullable=True),
        sa.Column("yellow_cards", sa.Integer(), nullable=True),
        sa.Column("red_cards", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_fact_player_match_player_id_dim_player"),
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["dim_match.match_id"],
            name=op.f("fk_fact_player_match_match_id_dim_match"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["dim_team.team_id"],
            name=op.f("fk_fact_player_match_team_id_dim_team"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact_player_match")),
        sa.UniqueConstraint(
            "player_id",
            "match_id",
            "source",
            name=op.f("uq_fact_player_match_player_id_match_id_source"),
        ),
    )
    op.create_index(
        op.f("ix_fact_player_match_player_id"), "fact_player_match", ["player_id"], unique=False
    )
    op.create_index(
        op.f("ix_fact_player_match_match_id"), "fact_player_match", ["match_id"], unique=False
    )
    op.create_table(
        "fact_team_match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("xg", sa.Float(), nullable=True),
        sa.Column("xga", sa.Float(), nullable=True),
        sa.Column("npxg", sa.Float(), nullable=True),
        sa.Column("npxga", sa.Float(), nullable=True),
        sa.Column("ppda", sa.Float(), nullable=True),
        sa.Column("ppda_allowed", sa.Float(), nullable=True),
        sa.Column("deep", sa.Integer(), nullable=True),
        sa.Column("deep_allowed", sa.Integer(), nullable=True),
        sa.Column("possession", sa.Float(), nullable=True),
        sa.Column("set_piece_xg", sa.Float(), nullable=True),
        sa.Column("set_piece_xga", sa.Float(), nullable=True),
        sa.Column("open_play_xga", sa.Float(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["dim_team.team_id"],
            name=op.f("fk_fact_team_match_team_id_dim_team"),
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["dim_match.match_id"],
            name=op.f("fk_fact_team_match_match_id_dim_match"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact_team_match")),
        sa.UniqueConstraint(
            "team_id",
            "match_id",
            "source",
            name=op.f("uq_fact_team_match_team_id_match_id_source"),
        ),
    )
    op.create_index(
        op.f("ix_fact_team_match_team_id"), "fact_team_match", ["team_id"], unique=False
    )
    op.create_index(
        op.f("ix_fact_team_match_match_id"), "fact_team_match", ["match_id"], unique=False
    )
    op.create_table(
        "fact_market_value",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("value_eur", sa.BigInteger(), nullable=True),
        sa.Column("tm_last_updated", sa.Date(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_fact_market_value_player_id_dim_player"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact_market_value")),
        sa.UniqueConstraint(
            "player_id",
            "source",
            "tm_last_updated",
            name=op.f("uq_fact_market_value_player_id_source_tm_last_updated"),
        ),
    )
    op.create_index(
        op.f("ix_fact_market_value_player_id"), "fact_market_value", ["player_id"], unique=False
    )
    op.create_table(
        "fact_player_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("fpl_status", sa.String(2), nullable=True),
        sa.Column("news", sa.Text(), nullable=True),
        sa.Column("chance_of_playing", sa.Integer(), nullable=True),
        sa.Column("contract_expiry", sa.Date(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_fact_player_status_player_id_dim_player"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact_player_status")),
        sa.UniqueConstraint(
            "player_id",
            "source",
            "fetched_at",
            name=op.f("uq_fact_player_status_player_id_source_fetched_at"),
        ),
    )
    op.create_index(
        op.f("ix_fact_player_status_player_id"), "fact_player_status", ["player_id"], unique=False
    )
    op.create_table(
        "source_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("fetched_at", TZ, nullable=False),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_snapshot")),
    )
    op.create_index(op.f("ix_source_snapshot_source"), "source_snapshot", ["source"], unique=False)
    op.create_table(
        "entity_map_review",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("team", sa.String(100), nullable=True),
        sa.Column("best_candidate", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.ForeignKeyConstraint(
            ["best_candidate"],
            ["dim_player.player_id"],
            name=op.f("fk_entity_map_review_best_candidate_dim_player"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_map_review")),
    )


def downgrade() -> None:
    """Drop every warehouse table."""
    for table in (
        "entity_map_review",
        "source_snapshot",
        "fact_player_status",
        "fact_market_value",
        "fact_team_match",
        "fact_player_match",
        "dim_match",
        "dim_player",
        "dim_team",
        "dim_season",
    ):
        op.drop_table(table)
