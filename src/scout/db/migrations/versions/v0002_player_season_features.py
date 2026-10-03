"""Materialised player_season_features (PRD §11).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create player_season_features."""
    op.create_table(
        "player_season_features",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season_mode", sa.String(10), nullable=False),
        sa.Column("position_group", sa.String(3), nullable=False),
        sa.Column("kpi", sa.String(40), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("raw_p90", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("shrunk", sa.Float(), nullable=True),
        sa.Column("percentile", sa.Float(), nullable=True),
        sa.Column("n_peers", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Float(), nullable=False),
        sa.Column("effective_minutes", sa.Float(), nullable=False),
        sa.Column("used_previous_season", sa.Boolean(), nullable=False),
        sa.Column("is_proxy", sa.Boolean(), nullable=False),
        sa.Column("padj_status", sa.String(12), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["dim_player.player_id"],
            name=op.f("fk_player_season_features_player_id_dim_player"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_season_features")),
        sa.UniqueConstraint(
            "player_id",
            "season_mode",
            "kpi",
            name=op.f("uq_player_season_features_player_id_season_mode_kpi"),
        ),
    )
    op.create_index(
        op.f("ix_player_season_features_player_id"),
        "player_season_features",
        ["player_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop player_season_features."""
    op.drop_index(op.f("ix_player_season_features_player_id"), table_name="player_season_features")
    op.drop_table("player_season_features")
