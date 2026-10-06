"""ML outputs stored in the warehouse: role archetypes and stats-implied values (PRD §8.10).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create player_role and player_value_score."""
    op.create_table(
        "player_role",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season_mode", sa.String(10), nullable=False),
        sa.Column("cluster", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("trained_at", TZ, nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_player_role_player_id_dim_player"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_role")),
        sa.UniqueConstraint(
            "player_id", "season_mode", name=op.f("uq_player_role_player_id_season_mode")
        ),
    )
    op.create_index(op.f("ix_player_role_player_id"), "player_role", ["player_id"], unique=False)
    op.create_table(
        "player_value_score",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.String(7), nullable=False),
        sa.Column("value_eur", sa.BigInteger(), nullable=False),
        sa.Column("value_source", sa.String(30), nullable=False),
        sa.Column("tm_last_updated", sa.Date(), nullable=False),
        sa.Column("value_is_stale", sa.Boolean(), nullable=False),
        sa.Column("implied_value_eur", sa.Float(), nullable=False),
        sa.Column("band_low_eur", sa.Float(), nullable=False),
        sa.Column("band_high_eur", sa.Float(), nullable=False),
        sa.Column("value_label", sa.String(12), nullable=False),
        sa.Column("trained_at", TZ, nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_player_value_score_player_id_dim_player"),
        ),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["dim_season.season_id"],
            name=op.f("fk_player_value_score_season_id_dim_season"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_value_score")),
        sa.UniqueConstraint(
            "player_id", "season_id", name=op.f("uq_player_value_score_player_id_season_id")
        ),
    )
    op.create_index(
        op.f("ix_player_value_score_player_id"), "player_value_score", ["player_id"], unique=False
    )


def downgrade() -> None:
    """Drop the ML output tables."""
    op.drop_index(op.f("ix_player_value_score_player_id"), table_name="player_value_score")
    op.drop_table("player_value_score")
    op.drop_index(op.f("ix_player_role_player_id"), table_name="player_role")
    op.drop_table("player_role")
