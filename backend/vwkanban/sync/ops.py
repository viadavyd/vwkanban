"""apply_op: the only writer of cards (plan §3.3).

1. per-board asyncio.Lock (one worker: commit order = response/broadcast order)
2. op_id already logged → return the stored ack (idempotent resend)
3. access + liveness checks, scoped to the board
4. UPDATE boards SET seq=seq+1, next_number=... RETURNING (row lock, allocation)
5. mutate; every written field gets field_meta[f] = {seq, client}
6. append to board_events, commit, ack
A reject rolls back, so the seq is not consumed.
"""

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.boards.deps import Membership
from vwkanban.boards.models import Board, Card, Status
from vwkanban.boards.schemas import CardOut
from vwkanban.errors import ApiError
from vwkanban.sync.fracindex import key_between
from vwkanban.sync.models import BoardEvent
from vwkanban.sync.schemas import Ack, CardCreate, CardDelete, CardUpdate, Op

_locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

_STATUS = {"not_found": 404, "gone": 410, "validation": 422, "conflict": 409, "forbidden": 403}


class Reject(Exception):
    def __init__(self, code: str, message: str, current: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current = current


def card_out(card: Card) -> dict:
    return CardOut.model_validate(card, from_attributes=True).model_dump(mode="json")


async def apply_op(db: AsyncSession, member: Membership, client_id: uuid.UUID, op: Op) -> Ack:
    board_id = member.board.id
    async with _locks[board_id]:
        # End the access check's read transaction (commit: rollback would expire `member`).
        await db.commit()
        prior = await db.scalar(select(BoardEvent).where(BoardEvent.op_id == op.op_id))
        if prior is not None:
            if prior.board_id != board_id:
                raise ApiError(422, "validation", "op_id already used")
            return Ack(op_id=op.op_id, seq=prior.seq, event=prior.payload)
        try:
            data = await _apply(db, member, client_id, op)
        except Reject as r:
            await db.rollback()
            raise ApiError(
                _STATUS[r.code], r.code, r.message, {"op_id": str(op.op_id), "current": r.current}
            ) from None
        seq = data.pop("_seq")
        event = {
            "seq": seq,
            "op_id": str(op.op_id),
            "client_id": str(client_id),
            "actor": {"id": str(member.user.id), "username": member.user.username},
            "kind": op.kind,
            "data": data,
        }
        db.add(
            BoardEvent(
                board_id=board_id,
                seq=seq,
                op_id=op.op_id,
                client_id=client_id,
                actor_id=member.user.id,
                kind=op.kind,
                payload=event,
            )
        )
        await db.commit()
        return Ack(op_id=op.op_id, seq=seq, event=event)


async def _next_seq(db: AsyncSession, board_id: uuid.UUID, numbers: int = 0) -> tuple[int, int]:
    """Advances the board's seq (and reserves `numbers` card numbers) under its row lock.
    Returns (seq, first reserved number)."""
    row = (
        await db.execute(
            update(Board)
            .where(Board.id == board_id)
            .values(
                seq=Board.seq + 1,
                next_number=Board.next_number + numbers,
                updated_at=func.now(),
            )
            .returning(Board.seq, Board.next_number)
        )
    ).one()
    return row.seq, row.next_number - numbers


def _meta(card: Card, fields: list[str], seq: int, client_id: uuid.UUID) -> None:
    stamp = {"seq": seq, "client": str(client_id)}
    card.field_meta = {**card.field_meta, **dict.fromkeys(fields, stamp)}


async def _card(db: AsyncSession, board_id: uuid.UUID, card_id: uuid.UUID) -> Card:
    card = await db.scalar(
        select(Card).where(Card.id == card_id, Card.board_id == board_id).with_for_update()
    )
    if card is None:
        raise Reject("not_found", "card not found")
    if card.deleted_at is not None:
        raise Reject("gone", f"#{card.number} was deleted")
    return card


async def _apply(db: AsyncSession, member: Membership, client_id: uuid.UUID, op: Op) -> dict:
    match op:
        case CardCreate():
            return await _create(db, member, client_id, op)
        case CardUpdate():
            return await _update(db, member, client_id, op)
        case CardDelete():
            return await _delete(db, member, client_id, op)
    raise AssertionError(op)


async def _position(
    db: AsyncSession,
    board_id: uuid.UUID,
    status_id: uuid.UUID,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
) -> str:
    """Key for an insert next to whichever neighbour is still live in the column, using the
    server's real neighbours (never the client's pairing); else at the end."""
    column = (
        Card.board_id == board_id,
        Card.status_id == status_id,
        Card.parent_card_id.is_(None),
        Card.deleted_at.is_(None),
    )

    async def pos_of(card_id: uuid.UUID | None) -> str | None:
        if card_id is None:
            return None
        return await db.scalar(select(Card.position).where(Card.id == card_id, *column))

    if (after := await pos_of(after_id)) is not None:
        upper = await db.scalar(
            select(func.min(Card.position)).where(*column, Card.position > after)
        )
        return key_between(after, upper)
    if (before := await pos_of(before_id)) is not None:
        lower = await db.scalar(
            select(func.max(Card.position)).where(*column, Card.position < before)
        )
        return key_between(lower, before)
    last = await db.scalar(select(func.max(Card.position)).where(*column))
    return key_between(last, None)


async def _create(db: AsyncSession, member: Membership, client_id: uuid.UUID, op: CardCreate):
    d = op.data
    board_id = member.board.id
    status = await db.scalar(
        select(Status.id).where(Status.id == d.status_id, Status.board_id == board_id)
    )
    if status is None:
        raise Reject("gone", "that column no longer exists")
    if await db.scalar(select(Card.id).where(Card.id == d.id)) is not None:
        raise Reject("validation", "card id already exists")
    seq, number = await _next_seq(db, board_id, numbers=1)
    card = Card(
        id=d.id,
        board_id=board_id,
        number=number,
        status_id=d.status_id,
        position=await _position(db, board_id, d.status_id, d.after_id, d.before_id),
        title=d.title,
        description=d.description,
        is_done=d.is_done,
        tags=d.tags,
        date=d.date,
        field_meta={},
        created_by=member.user.id,
    )
    _meta(card, ["title", "description", "tags", "date", "is_done", "position"], seq, client_id)
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return {"_seq": seq, "card": card_out(card)}


async def _update(db: AsyncSession, member: Membership, client_id: uuid.UUID, op: CardUpdate):
    board_id = member.board.id
    card = await _card(db, board_id, op.data.id)
    fields = op.data.fields.model_dump(exclude_unset=True)
    seq, _ = await _next_seq(db, board_id)
    for name, value in fields.items():  # is_done: last write wins
        setattr(card, name, value)
    card.updated_at = func.now()
    _meta(card, list(fields), seq, client_id)
    await db.flush()
    await db.refresh(card)
    return {"_seq": seq, "card": card_out(card)}


async def _delete(db: AsyncSession, member: Membership, client_id: uuid.UUID, op: CardDelete):
    board_id = member.board.id
    card = await _card(db, board_id, op.data.id)
    children = (
        await db.scalars(
            select(Card)
            .where(Card.parent_card_id == card.id, Card.deleted_at.is_(None))
            .with_for_update()
        )
    ).all()
    seq, _ = await _next_seq(db, board_id)
    stamp = {"seq": seq, "client": str(client_id)}
    for c in (card, *children):
        c.deleted_at = func.now()
        c.updated_at = func.now()
        _meta(c, ["deleted"], seq, client_id)
    await db.flush()
    return {
        "_seq": seq,
        "id": str(card.id),
        "deleted_ids": [str(c.id) for c in (card, *children)],
        "field_meta": {"deleted": stamp},
    }
