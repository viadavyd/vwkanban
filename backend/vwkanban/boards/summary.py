"""Dashboard tiles: every board the user is a member of, with card counts per column,
in one GROUP BY. Counts are live top-level cards (children are checklist items)."""

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.boards.models import Board, BoardMember, Card, Status
from vwkanban.boards.schemas import DashboardItem, StatusCount, Summary


async def dashboard(
    db: AsyncSession, user_id: uuid.UUID, board_id: uuid.UUID | None = None
) -> list[DashboardItem]:
    stmt = (
        select(
            Board.id,
            Board.title,
            Board.updated_at,
            BoardMember.role,
            Status.name,
            Status.color,
            func.count(Card.id).label("count"),
            func.count(Card.id).filter(Card.is_done).label("done"),
        )
        .select_from(BoardMember)
        .join(Board, Board.id == BoardMember.board_id)
        .outerjoin(Status, Status.board_id == Board.id)
        .outerjoin(
            Card,
            and_(
                Card.status_id == Status.id,
                Card.deleted_at.is_(None),
                Card.parent_card_id.is_(None),
            ),
        )
        .where(BoardMember.user_id == user_id)
        .group_by(Board.id, BoardMember.role, Status.id)
        .order_by(Board.created_at, Board.id, Status.position, Status.id)
    )
    if board_id is not None:
        stmt = stmt.where(Board.id == board_id)

    items: dict[uuid.UUID, DashboardItem] = {}
    for row in await db.execute(stmt):
        item = items.get(row.id)
        if item is None:
            item = items[row.id] = DashboardItem(
                id=row.id,
                title=row.title,
                updated_at=row.updated_at,
                role=row.role,
                summary=Summary(total=0, done=0, by_status=[]),
            )
        if row.name is not None:  # a board with no columns has one all-NULL status row
            s = item.summary
            s.by_status.append(StatusCount(name=row.name, color=row.color, count=row.count))
            s.total += row.count
            s.done += row.done
    return list(items.values())
