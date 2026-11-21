from fastapi import APIRouter, Request
from sqlalchemy import delete, func, select, update

from vwkanban.auth.deps import CurrentUser, Db
from vwkanban.auth.models import User
from vwkanban.boards.deps import Member, Owner
from vwkanban.boards.models import Board, BoardMember, Card, Status
from vwkanban.boards.schemas import (
    BoardDetail,
    BoardIn,
    BoardOut,
    CardOut,
    DashboardItem,
    MemberOut,
    StatusOut,
)
from vwkanban.boards.summary import dashboard
from vwkanban.ids import uuid7
from vwkanban.sync.ws import CLOSE_BOARD_GONE

router = APIRouter(prefix="/boards", tags=["boards"])

# New boards get these columns. Positions are fractional-index keys (sync/fracindex).
SEED_STATUSES = (("Todo", "gray", "a0"), ("Doing", "blue", "a1"), ("Done", "green", "a2"))


async def _item(db: Db, user: CurrentUser, board_id) -> DashboardItem:
    return (await dashboard(db, user.id, board_id))[0]


@router.get("")
async def list_boards(user: CurrentUser, db: Db) -> list[DashboardItem]:
    return await dashboard(db, user.id)


@router.post("", status_code=201)
async def create_board(body: BoardIn, user: CurrentUser, db: Db) -> DashboardItem:
    board = Board(id=uuid7(), title=body.title, created_by=user.id)
    db.add(board)
    await db.flush()
    db.add(BoardMember(board_id=board.id, user_id=user.id, role="owner"))
    db.add_all(
        Status(id=uuid7(), board_id=board.id, name=name, color=color, position=pos)
        for name, color, pos in SEED_STATUSES
    )
    await db.commit()
    return await _item(db, user, board.id)


@router.patch("/{board_id}")
async def rename_board(body: BoardIn, owner: Owner, db: Db) -> DashboardItem:
    await db.execute(
        update(Board)
        .where(Board.id == owner.board.id)
        .values(title=body.title, updated_at=func.now())
    )
    await db.commit()
    return await _item(db, owner.user, owner.board.id)


@router.delete("/{board_id}", status_code=204)
async def delete_board(owner: Owner, db: Db, request: Request) -> None:
    await db.execute(delete(Board).where(Board.id == owner.board.id))
    await db.commit()
    request.app.state.hub.close_board(owner.board.id, CLOSE_BOARD_GONE)


@router.get("/{board_id}")
async def get_board(member: Member, db: Db) -> BoardDetail:
    board = member.board
    statuses = await db.scalars(
        select(Status).where(Status.board_id == board.id).order_by(Status.position, Status.id)
    )
    members = await db.execute(
        select(User.id, User.username, BoardMember.role)
        .join(BoardMember, BoardMember.user_id == User.id)
        .where(BoardMember.board_id == board.id)
        .order_by(User.username)
    )
    # Live cards, top-level and children, served by the partial indexes on cards.
    cards = await db.scalars(
        select(Card)
        .where(Card.board_id == board.id, Card.deleted_at.is_(None))
        .order_by(Card.status_id, Card.parent_card_id, Card.position)
    )
    return BoardDetail(
        board=BoardOut.model_validate(board, from_attributes=True),
        seq=board.seq,
        statuses=[StatusOut.model_validate(s, from_attributes=True) for s in statuses],
        cards=[CardOut.model_validate(c, from_attributes=True) for c in cards],
        members=[MemberOut(user_id=m.id, username=m.username, role=m.role) for m in members],
    )
