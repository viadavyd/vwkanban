"""The board op log (plan §2 board_events): order of truth, idempotent resends, and (M4)
reconnect replay. Conflict and undo checks never read it; they use cards.field_meta."""

import datetime as dt
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from vwkanban.db import Base

# Events kept per board; older ones are trimmed on startup (reconnect → resync).
EVENT_RETENTION = 10_000


class BoardEvent(Base):
    __tablename__ = "board_events"

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    op_id: Mapped[uuid.UUID] = mapped_column(unique=True)  # client-generated; dedups resends
    client_id: Mapped[uuid.UUID]  # browser tab
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)  # the event as sent to clients
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def trim_events(db: AsyncSession, keep: int = EVENT_RETENTION) -> None:
    """Keeps the last `keep` events per board (plan §2 retention)."""
    await db.execute(
        text(
            "DELETE FROM board_events e USING boards b"
            " WHERE e.board_id = b.id AND e.seq <= b.seq - :keep"
        ),
        {"keep": keep},
    )
    await db.commit()
