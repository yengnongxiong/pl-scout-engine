"""Why entity resolution sent a record to review (``entity_map_review.reason``).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the reason column (rows from earlier builds have none until the next build)."""
    with op.batch_alter_table("entity_map_review") as batch:
        batch.add_column(sa.Column("reason", sa.String(200), nullable=True))


def downgrade() -> None:
    """Drop the reason column."""
    with op.batch_alter_table("entity_map_review") as batch:
        batch.drop_column("reason")
