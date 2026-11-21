"""Board sharing (plan §3.1): list for members; add and remove for the owner. Removing a
member closes their open sockets on the board (4403)."""

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from vwkanban.auth.deps import Db
from vwkanban.auth.models import User
from vwkanban.auth.users import find_user
from vwkanban.boards.deps import Member, Owner
from vwkanban.boards.models import BoardMember
from vwkanban.boards.schemas import MemberOut
from vwkanban.errors import ApiError
from vwkanban.sync.ws import CLOSE_NOT_MEMBER

router = APIRouter(prefix="/boards", tags=["members"])


class MemberIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


async def _members(db: Db, board_id: uuid.UUID) -> list[MemberOut]:
    rows = await db.execute(
        select(User.id, User.username, BoardMember.role)
        .join(BoardMember, BoardMember.user_id == User.id)
        .where(BoardMember.board_id == board_id)
        .order_by(User.username)
    )
    return [MemberOut(user_id=r.id, username=r.username, role=r.role) for r in rows]


@router.get("/{board_id}/members")
async def list_members(member: Member, db: Db) -> list[MemberOut]:
    return await _members(db, member.board.id)


@router.post("/{board_id}/members", status_code=201)
async def add_member(body: MemberIn, owner: Owner, db: Db) -> MemberOut:
    user = await find_user(db, body.username)
    if user is None:
        raise ApiError(404, "not_found", f"no user named {body.username.strip()!r}")
    added = await db.scalar(
        insert(BoardMember)
        .values(board_id=owner.board.id, user_id=user.id, role="editor")
        .on_conflict_do_nothing()
        .returning(BoardMember.user_id)
    )
    if added is None:
        raise ApiError(409, "conflict", f"{user.username} is already a member")
    await db.commit()
    return MemberOut(user_id=user.id, username=user.username, role="editor")


@router.delete("/{board_id}/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, owner: Owner, db: Db, request: Request) -> None:
    role = await db.scalar(
        select(BoardMember.role).where(
            BoardMember.board_id == owner.board.id, BoardMember.user_id == user_id
        )
    )
    if role is None:
        raise ApiError(404, "not_found", "not a member of this board")
    if role == "owner":
        raise ApiError(422, "validation", "the board owner can't be removed")
    await db.execute(
        delete(BoardMember).where(
            BoardMember.board_id == owner.board.id, BoardMember.user_id == user_id
        )
    )
    await db.commit()
    request.app.state.hub.close_user(owner.board.id, user_id, CLOSE_NOT_MEMBER)
