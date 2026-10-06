"""Goalkeeper columns on fact_player_match: saves, goals conceded, penalties saved (S2).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("saves", "goals_conceded", "penalties_saved")


def upgrade() -> None:
    """Add the goalkeeper columns (nullable: older rows simply do not have them)."""
    with op.batch_alter_table("fact_player_match") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the goalkeeper columns."""
    with op.batch_alter_table("fact_player_match") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
