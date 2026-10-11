"""Possession from ESPN: ``dim_match.espn_event_id`` replaces the FotMob game key (ADR-0002).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the FotMob game key for ESPN's event id; FotMob rows can no longer be rebuilt."""
    op.execute("DELETE FROM fact_team_match WHERE source = 'fotmob'")
    with op.batch_alter_table("dim_match") as batch:
        batch.drop_constraint("uq_dim_match_fotmob_game", type_="unique")
        batch.drop_column("fotmob_game")
        batch.add_column(sa.Column("espn_event_id", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_dim_match_espn_event_id", ["espn_event_id"])


def downgrade() -> None:
    """Restore the FotMob game key column (empty) and drop the ESPN event id."""
    op.execute("DELETE FROM fact_team_match WHERE source = 'espn'")
    with op.batch_alter_table("dim_match") as batch:
        batch.drop_constraint("uq_dim_match_espn_event_id", type_="unique")
        batch.drop_column("espn_event_id")
        batch.add_column(sa.Column("fotmob_game", sa.String(200), nullable=True))
        batch.create_unique_constraint("uq_dim_match_fotmob_game", ["fotmob_game"])
