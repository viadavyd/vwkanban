"""boards, board_members, statuses and cards

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "boards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("next_number", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="boards_title_len"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "board_members",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor')", name="board_members_role"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("board_id", "user_id"),
    )
    op.create_index(op.f("ix_board_members_user_id"), "board_members", ["user_id"], unique=False)
    op.create_table(
        "statuses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("position", sa.Text(collation="C"), nullable=False),
        sa.CheckConstraint(
            "color IN ('red', 'yellow', 'blue', 'green', 'purple', 'orange', 'pink', 'gray')",
            name="statuses_color",
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 40", name="statuses_name_len"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("board_id", "name", name="statuses_board_name"),
    )
    op.create_index(
        "ix_statuses_board_position", "statuses", ["board_id", "position"], unique=False
    )
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parent_card_id", sa.Uuid(), nullable=True),
        sa.Column("status_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Text(collation="C"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("is_done", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column(
            "field_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(parent_card_id IS NULL) = (status_id IS NOT NULL)", name="cards_child_xor_status"
        ),
        sa.CheckConstraint("char_length(description) <= 20000", name="cards_description_len"),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 300", name="cards_title_len"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["parent_card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["status_id"], ["statuses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("board_id", "number", name="cards_board_number"),
    )
    op.create_index(
        "ix_cards_children",
        "cards",
        ["parent_card_id", "position"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_cards_column",
        "cards",
        ["board_id", "status_id", "position"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL AND parent_card_id IS NULL"),
    )


def downgrade() -> None:

    op.drop_index(
        "ix_cards_column",
        table_name="cards",
        postgresql_where=sa.text("deleted_at IS NULL AND parent_card_id IS NULL"),
    )
    op.drop_index(
        "ix_cards_children", table_name="cards", postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.drop_table("cards")
    op.drop_index("ix_statuses_board_position", table_name="statuses")
    op.drop_table("statuses")
    op.drop_index(op.f("ix_board_members_user_id"), table_name="board_members")
    op.drop_table("board_members")
    op.drop_table("boards")
