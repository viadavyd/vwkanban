"""Board → CSV (plan §3.6 export order): columns by position, cards by position within
their column, each card's children right after it. Only live cards are exported."""

import uuid
from collections import defaultdict

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.boards.due import format_due
from vwkanban.boards.models import Card, Status
from vwkanban.csvio.format import serialize


async def export_board(db: AsyncSession, board_id: uuid.UUID) -> bytes:
    statuses = (
        await db.execute(
            select(Status.id, Status.name)
            .where(Status.board_id == board_id)
            .order_by(Status.position, Status.id)
        )
    ).all()
    cards = (
        await db.execute(
            select(
                Card.id,
                Card.number,
                Card.status_id,
                Card.parent_card_id,
                Card.title,
                Card.date,
                Card.due_time,
                Card.is_done,
                Card.tags,
                Card.description,
            )
            .where(Card.board_id == board_id, Card.deleted_at.is_(None))
            .order_by(Card.position, Card.id)
        )
    ).all()
    by_status: defaultdict[uuid.UUID, list] = defaultdict(list)
    kids: defaultdict[uuid.UUID, list] = defaultdict(list)
    for c in cards:
        if c.parent_card_id is None:
            by_status[c.status_id].append(c)
        else:
            kids[c.parent_card_id].append(c)

    def row(c, status: str, parent: str) -> dict[str, str]:
        return {
            "id": str(c.number),
            "title": c.title,
            "status": status,
            "date": format_due(c.date, c.due_time) or "",
            "parent": parent,
            "is_done": "true" if c.is_done else "false",
            "tags": ";".join(c.tags),
            "description": c.description,
        }

    rows = []
    for status_id, name in statuses:
        for c in by_status[status_id]:
            rows.append(row(c, name, ""))
            rows.extend(row(k, "", str(c.number)) for k in kids[c.id])
    return await anyio.to_thread.run_sync(serialize, rows)
