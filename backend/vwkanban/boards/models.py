"""Boards, members, statuses (columns) and cards — the schema in plan §2.

Cards are schema-only until M3a: every card write goes through `sync/ops.py::apply_op`.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vwkanban.db import Base
from vwkanban.ids import uuid7

ROLES = ("owner", "editor")
COLORS = ("red", "yellow", "blue", "green", "purple", "orange", "pink", "gray")
BOARD_TITLE_MAX = 120
STATUS_NAME_MAX = 40
CARD_TITLE_MAX = 300
CARD_DESCRIPTION_MAX = 20_000
# Fractional-index keys compare byte-wise ("A" < "Z" < "a"); a locale collation would
# reorder them, so positions always use the "C" collation.
POSITION = Text(collation="C")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Board(Base):
    __tablename__ = "boards"
    __table_args__ = (
        CheckConstraint(
            f"char_length(title) BETWEEN 1 AND {BOARD_TITLE_MAX}", name="boards_title_len"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Last op sequence and next card number; both advance in one UPDATE under the row lock.
    seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    next_number: Mapped[int] = mapped_column(Integer, server_default="1")


class BoardMember(Base):
    __tablename__ = "board_members"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="board_members_role"),)

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(Text)


class Status(Base):
    __tablename__ = "statuses"
    __table_args__ = (
        UniqueConstraint("board_id", "name", name="statuses_board_name"),
        CheckConstraint(
            f"char_length(name) BETWEEN 1 AND {STATUS_NAME_MAX}", name="statuses_name_len"
        ),
        CheckConstraint(_in("color", COLORS), name="statuses_color"),
        Index("ix_statuses_board_position", "board_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)
    position: Mapped[str] = mapped_column(POSITION)
    # Per field: {"name"|"color"|"position"|"created": {"seq", "client"}}; read by undo checks.
    field_meta: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("board_id", "number", name="cards_board_number"),
        # A child has no column; a top-level card always has one.
        CheckConstraint(
            "(parent_card_id IS NULL) = (status_id IS NOT NULL)", name="cards_child_xor_status"
        ),
        CheckConstraint(
            f"char_length(title) BETWEEN 1 AND {CARD_TITLE_MAX}", name="cards_title_len"
        ),
        CheckConstraint(
            f"char_length(description) <= {CARD_DESCRIPTION_MAX}", name="cards_description_len"
        ),
        Index(
            "ix_cards_column",
            "board_id",
            "status_id",
            "position",
            postgresql_where=text("deleted_at IS NULL AND parent_card_id IS NULL"),
        ),
        Index(
            "ix_cards_children",
            "parent_card_id",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    parent_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE")
    )
    status_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("statuses.id", ondelete="RESTRICT")
    )
    position: Mapped[str] = mapped_column(POSITION)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    is_done: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    date: Mapped[dt.date | None] = mapped_column(Date)  # due date
    # Per field: {"title": {"seq": 41, "client": "<uuid>"}, ...}; read by conflict/undo checks.
    field_meta: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
