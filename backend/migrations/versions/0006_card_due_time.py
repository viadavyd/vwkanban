"""cards.due_time (an optional time on the due date)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("due_time", sa.Time(), nullable=True))
    op.create_check_constraint(
        "cards_due_time_needs_date", "cards", "due_time IS NULL OR date IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint("cards_due_time_needs_date", "cards", type_="check")
    op.drop_column("cards", "due_time")
