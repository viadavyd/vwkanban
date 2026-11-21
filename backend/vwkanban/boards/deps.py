"""Board access. Every route touching a board depends on `require_member` (or
`require_owner`). A non-member gets 404, so board ids don't reveal which boards exist."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.auth.deps import CurrentUser, Db
from vwkanban.auth.models import User
from vwkanban.boards.models import Board, BoardMember
from vwkanban.errors import ApiError


@dataclass(frozen=True)
class Membership:
    board: Board
    user: User
    role: str


async def load_membership(db: AsyncSession, board_id: uuid.UUID, user: User) -> Membership | None:
    """`user`'s membership of the board, or None (no such board, or not a member)."""
    row = (
        await db.execute(
            select(Board, BoardMember.role)
            .join(BoardMember, BoardMember.board_id == Board.id)
            .where(Board.id == board_id, BoardMember.user_id == user.id)
        )
    ).first()
    return None if row is None else Membership(board=row[0], user=user, role=row[1])


async def is_member(db: AsyncSession, board_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """A cheap membership check (one indexed row, no board load), for every op."""
    found = await db.scalar(
        select(BoardMember.role).where(
            BoardMember.board_id == board_id, BoardMember.user_id == user_id
        )
    )
    return found is not None


async def require_member(board_id: uuid.UUID, user: CurrentUser, db: Db) -> Membership:
    member = await load_membership(db, board_id, user)
    if member is None:
        raise ApiError(404, "not_found", "board not found")
    return member


Member = Annotated[Membership, Depends(require_member)]


async def require_owner(member: Member) -> Membership:
    if member.role != "owner":
        raise ApiError(403, "forbidden", "only the board owner can do this")
    return member


Owner = Annotated[Membership, Depends(require_owner)]
