"""apply_op: the only writer of cards (plan §3.3).

1. per-board asyncio.Lock (one worker: commit order = response/broadcast order)
2. op_id already logged → return the stored ack (idempotent resend)
3. access + liveness checks, scoped to the board
4. UPDATE boards SET seq=seq+1, next_number=... RETURNING (row lock, allocation)
5. conflict checks against field_meta: text fields of card.update against `base_seq`,
   and every touched field of an undo; mutate; every written field gets
   field_meta[f] = {seq, client}
6. append to board_events, commit, broadcast the event to the board's sockets (sender
   included: its client drops the pending op by op_id), ack
A reject rolls back, so the seq is not consumed. The membership is re-checked under the
lock, so an op racing the member's removal is refused.
"""

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.auth.models import User
from vwkanban.boards.deps import Membership, is_member
from vwkanban.boards.models import COLORS, Board, Card, Status
from vwkanban.boards.schemas import CardOut, StatusOut
from vwkanban.csvio.import_ import Parsed
from vwkanban.errors import ApiError
from vwkanban.ids import uuid7
from vwkanban.sync.fracindex import key_between
from vwkanban.sync.hub import Hub
from vwkanban.sync.models import BoardEvent
from vwkanban.sync.schemas import (
    TEXT_FIELDS,
    Ack,
    CardCreate,
    CardDelete,
    CardMove,
    CardRestore,
    CardUpdate,
    Op,
    StatusCreate,
    StatusDelete,
    StatusMove,
    StatusUpdate,
)

_locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)


def board_lock(board_id: uuid.UUID) -> asyncio.Lock:
    """Serializes a board's ops (and a socket's registration, so replay has no gap)."""
    return _locks[board_id]


_STATUS = {"not_found": 404, "gone": 410, "validation": 422, "conflict": 409, "forbidden": 403}


class Reject(Exception):
    def __init__(self, code: str, message: str, current: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current = current


def card_out(card: Card) -> dict:
    return CardOut.model_validate(card, from_attributes=True).model_dump(mode="json")


def status_out(status: Status) -> dict:
    return StatusOut.model_validate(status, from_attributes=True).model_dump(mode="json")


async def apply_op(
    db: AsyncSession,
    member: Membership,
    client_id: uuid.UUID,
    op: Op,
    hub: Hub | None = None,
) -> Ack:
    board_id = member.board.id
    async with board_lock(board_id):
        await _check_member(db, member, op.op_id)
        prior = await db.scalar(select(BoardEvent).where(BoardEvent.op_id == op.op_id))
        if prior is not None:
            if prior.board_id != board_id:
                raise ApiError(422, "validation", "op_id already used")
            return Ack(op_id=op.op_id, seq=prior.seq, event=prior.payload)
        try:
            data = await _apply(_Ctx(db, member, client_id, op))
        except Reject as r:
            await db.rollback()
            raise ApiError(
                _STATUS[r.code], r.code, r.message, {"op_id": str(op.op_id), "current": r.current}
            ) from None
        seq = data.pop("_seq")
        event = await _commit_event(db, member, client_id, op.op_id, op.kind, seq, data, hub)
        return Ack(op_id=op.op_id, seq=seq, event=event)


async def _check_member(db: AsyncSession, member: Membership, op_id: uuid.UUID | None) -> None:
    """Under the board lock: ends the access check's read transaction (commit: rollback
    would expire `member`) and re-checks the membership, so a write racing the member's
    removal is refused."""
    await db.commit()
    if not await is_member(db, member.board.id, member.user.id):
        raise ApiError(
            403,
            "forbidden",
            "you are no longer a member of this board",
            {"op_id": str(op_id), "current": None} if op_id else None,
        )


async def _commit_event(
    db: AsyncSession,
    member: Membership,
    client_id: uuid.UUID,
    op_id: uuid.UUID,
    kind: str,
    seq: int,
    data: dict,
    hub: Hub | None,
) -> dict:
    """Steps 6-7 of the pipeline: log the event, commit, broadcast it to the board's
    sockets (still under the board lock, so broadcast order = seq order)."""
    event = {
        "seq": seq,
        "op_id": str(op_id),
        "client_id": str(client_id),
        "actor": {"id": str(member.user.id), "username": member.user.username},
        "kind": kind,
        "data": data,
    }
    db.add(
        BoardEvent(
            board_id=member.board.id,
            seq=seq,
            op_id=op_id,
            client_id=client_id,
            actor_id=member.user.id,
            kind=kind,
            payload=event,
        )
    )
    await db.commit()
    if hub is not None:
        hub.broadcast(member.board.id, {"t": "event", **event})
    return event


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


class _Ctx:
    """One op being applied: who sends it, on which board."""

    def __init__(self, db: AsyncSession, member: Membership, client_id: uuid.UUID, op: Op):
        self.db = db
        self.member = member
        self.board_id = member.board.id
        self.client_id = client_id
        self.op = op

    async def next_seq(self, numbers: int = 0) -> tuple[int, int]:
        return await _next_seq(self.db, self.board_id, numbers)

    def stamp(self, row: Card | Status, fields: list[str], seq: int) -> None:
        stamp = {"seq": seq, "client": str(self.client_id)}
        row.field_meta = {**row.field_meta, **dict.fromkeys(fields, stamp)}

    def stale(self, meta: dict, fields: list[str]) -> tuple[str, dict] | None:
        """The first of `fields` another client wrote after the op's `base_seq`, with its
        stamp. Reads only field_meta, never the event log (so trimming can't fail open)."""
        for f in fields:
            s = meta.get(f)
            if s and s["seq"] > self.op.base_seq and s["client"] != str(self.client_id):
                return f, s
        return None

    async def undo_check(self, meta: dict, fields: list[str], current: Any) -> None:
        """An undo must not revert a teammate's newer write (plan §3.2): reject if any field
        it touches was written by another client after the undone op (`base_seq`). The
        event log only names who, for the message."""
        if self.op.undo and (hit := self.stale(meta, fields)):
            raise Reject("conflict", f"can't undo: changed by {await self.who(hit[1])}", current)

    async def who(self, stamp: dict | None) -> str:
        """Who wrote a field_meta stamp, for messages ("another user" once its event has
        been trimmed from the log)."""
        name = None
        if stamp:
            name = await self.db.scalar(
                select(User.username)
                .join(BoardEvent, BoardEvent.actor_id == User.id)
                .where(BoardEvent.board_id == self.board_id, BoardEvent.seq == stamp["seq"])
            )
        return name or "another user"


async def _apply(ctx: _Ctx) -> dict:
    match ctx.op:
        case CardCreate():
            return await _create(ctx, ctx.op)
        case CardUpdate():
            return await _update(ctx, ctx.op)
        case CardDelete():
            return await _delete(ctx, ctx.op)
        case CardMove():
            return await _move(ctx, ctx.op)
        case CardRestore():
            return await _restore(ctx, ctx.op)
        case StatusCreate():
            return await _status_create(ctx, ctx.op)
        case StatusUpdate():
            return await _status_update(ctx, ctx.op)
        case StatusMove():
            return await _status_move(ctx, ctx.op)
        case StatusDelete():
            return await _status_delete(ctx, ctx.op)
    raise AssertionError(ctx.op)


# --- positions -------------------------------------------------------------------------


async def _key_in(
    db: AsyncSession,
    model: type[Card] | type[Status],
    scope: tuple,
    after_id: uuid.UUID | None,
    before_id: uuid.UUID | None,
) -> str:
    """Key for an insert into the list `scope` selects, next to whichever neighbour is
    still in it, using the server's real neighbours (never the client's pairing); else at
    the end. The only place keys are computed."""

    async def pos_of(row_id: uuid.UUID | None) -> str | None:
        if row_id is None:
            return None
        return await db.scalar(select(model.position).where(model.id == row_id, *scope))

    if (after := await pos_of(after_id)) is not None:
        upper = await db.scalar(
            select(func.min(model.position)).where(*scope, model.position > after)
        )
        return key_between(after, upper)
    if (before := await pos_of(before_id)) is not None:
        lower = await db.scalar(
            select(func.max(model.position)).where(*scope, model.position < before)
        )
        return key_between(lower, before)
    last = await db.scalar(select(func.max(model.position)).where(*scope))
    return key_between(last, None)


def _column(board_id: uuid.UUID, status_id: uuid.UUID, exclude: uuid.UUID | None = None):
    """The live top-level cards of a column (optionally without one card)."""
    scope = (
        Card.board_id == board_id,
        Card.status_id == status_id,
        Card.parent_card_id.is_(None),
        Card.deleted_at.is_(None),
    )
    return (*scope, Card.id != exclude) if exclude else scope


def _siblings(parent_id: uuid.UUID):
    return (Card.parent_card_id == parent_id, Card.deleted_at.is_(None))


# --- cards -----------------------------------------------------------------------------


async def _card(ctx: _Ctx, card_id: uuid.UUID) -> Card:
    card = await ctx.db.scalar(
        select(Card).where(Card.id == card_id, Card.board_id == ctx.board_id).with_for_update()
    )
    if card is None:
        raise Reject("not_found", "card not found")
    if card.deleted_at is not None:
        who = await ctx.who(card.field_meta.get("deleted"))
        raise Reject("gone", f"#{card.number} was deleted by {who}")
    return card


async def _status_live(ctx: _Ctx, status_id: uuid.UUID) -> bool:
    found = await ctx.db.scalar(
        select(Status.id).where(Status.id == status_id, Status.board_id == ctx.board_id)
    )
    return found is not None


async def _create(ctx: _Ctx, op: CardCreate):
    d = op.data
    db = ctx.db
    if d.parent_id is not None:
        return await _create_child(ctx, op)
    if not await _status_live(ctx, d.status_id):
        raise Reject("gone", "that column no longer exists")
    ids = [d.id, *(ch.id for ch in d.children)]
    if len(set(ids)) != len(ids) or await db.scalar(select(Card.id).where(Card.id.in_(ids))):
        raise Reject("validation", "card id already exists")
    seq, number = await ctx.next_seq(numbers=len(ids))

    def new(data, **place) -> Card:
        card = Card(
            id=data.id,
            board_id=ctx.board_id,
            title=data.title,
            description=data.description,
            is_done=data.is_done,
            tags=data.tags,
            date=data.date,
            field_meta={},
            created_by=ctx.member.user.id,
            **place,
        )
        ctx.stamp(card, _CREATED_FIELDS, seq)
        return card

    scope = _column(ctx.board_id, d.status_id)
    position = await _key_in(db, Card, scope, d.after_id, d.before_id)
    card = new(d, number=number, status_id=d.status_id, position=position)
    db.add(card)
    await db.flush()  # the parent row exists before its children reference it
    children, key = [], None
    for i, ch in enumerate(d.children, start=1):
        key = key_between(key, None)
        children.append(new(ch, number=number + i, parent_card_id=card.id, position=key))
    db.add_all(children)
    await db.flush()
    for c in (card, *children):
        await db.refresh(c)
    data: dict = {"_seq": seq, "card": card_out(card)}
    if children:
        data["children"] = [card_out(c) for c in children]
    return data


async def _create_child(ctx: _Ctx, op: CardCreate):
    """`o`/`O` in card mode: a child next to its siblings. The parent must be live and
    top-level (depth 1)."""
    d = op.data
    db = ctx.db
    parent = await _card(ctx, d.parent_id)
    if parent.parent_card_id is not None:
        raise Reject("validation", "a child card can't have children")
    if await db.scalar(select(Card.id).where(Card.id == d.id)) is not None:
        raise Reject("validation", "card id already exists")
    seq, number = await ctx.next_seq(numbers=1)
    card = Card(
        id=d.id,
        board_id=ctx.board_id,
        number=number,
        parent_card_id=parent.id,
        position=await _key_in(db, Card, _siblings(parent.id), d.after_id, d.before_id),
        title=d.title,
        description=d.description,
        is_done=d.is_done,
        tags=d.tags,
        date=d.date,
        field_meta={},
        created_by=ctx.member.user.id,
    )
    ctx.stamp(card, _CREATED_FIELDS, seq)
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return {"_seq": seq, "card": card_out(card)}


_CREATED_FIELDS = ["title", "description", "tags", "date", "is_done", "position"]

_FIELD_NAMES = {"title": "title", "description": "description", "tags": "tags", "date": "due date"}


async def _update(ctx: _Ctx, op: CardUpdate):
    """Text fields: optimistic concurrency against the frozen `base_seq` (plan §3.2); a
    stale write is refused with the card's current state, so the client keeps its draft.
    is_done: last write wins (except as an undo)."""
    card = await _card(ctx, op.data.id)
    fields = op.data.fields.model_dump(exclude_unset=True)
    text = [f for f in TEXT_FIELDS if f in fields]
    if not ctx.op.undo and (hit := ctx.stale(card.field_meta, text)):
        who = await ctx.who(hit[1])
        what = _FIELD_NAMES[hit[0]]
        raise Reject("conflict", f"#{card.number}'s {what} was changed by {who}", card_out(card))
    await ctx.undo_check(card.field_meta, list(fields), card_out(card))
    seq, _ = await ctx.next_seq()
    for name, value in fields.items():  # is_done: last write wins
        setattr(card, name, value)
    card.updated_at = func.now()
    ctx.stamp(card, list(fields), seq)
    await ctx.db.flush()
    await ctx.db.refresh(card)
    return {"_seq": seq, "card": card_out(card)}


async def _delete(ctx: _Ctx, op: CardDelete):
    card = await _card(ctx, op.data.id)
    await ctx.undo_check(card.field_meta, ["deleted"], card_out(card))
    children = (
        await ctx.db.scalars(select(Card).where(*_siblings(card.id)).with_for_update())
    ).all()
    seq, _ = await ctx.next_seq()
    for c in (card, *children):
        c.deleted_at = func.now()
        c.updated_at = func.now()
        ctx.stamp(c, ["deleted"], seq)
    await ctx.db.flush()
    return {
        "_seq": seq,
        "id": str(card.id),
        "deleted_ids": [str(c.id) for c in (card, *children)],
        "field_meta": {"deleted": {"seq": seq, "client": str(ctx.client_id)}},
    }


async def _move(ctx: _Ctx, op: CardMove):
    """LWW (plan §3.2): the card and the target column must be live, else `gone`.
    Children follow their parent (they reference it and have no column)."""
    d = op.data
    card = await _card(ctx, d.id)
    if card.parent_card_id is not None:
        raise Reject("validation", "a child card moves with its parent")
    if not await _status_live(ctx, d.status_id):
        raise Reject("gone", "that column no longer exists", card_out(card))
    await ctx.undo_check(card.field_meta, ["position"], card_out(card))
    seq, _ = await ctx.next_seq()
    scope = _column(ctx.board_id, d.status_id, exclude=card.id)
    card.position = await _key_in(ctx.db, Card, scope, d.after_id, d.before_id)
    card.status_id = d.status_id
    card.updated_at = func.now()
    ctx.stamp(card, ["position"], seq)
    await ctx.db.flush()
    await ctx.db.refresh(card)
    return {"_seq": seq, "card": card_out(card)}


async def _restore(ctx: _Ctx, op: CardRestore):
    """Undo of a delete: brings back the card and the children that delete took with it
    (same `deleted` stamp); children deleted on their own earlier stay deleted. A card
    purged with its column (plan §2 status delete rule) is `gone`."""
    db = ctx.db
    card = await db.scalar(select(Card).where(Card.id == op.data.id).with_for_update())
    if card is None:
        raise Reject("gone", "that card is gone for good (its column was deleted)")
    if card.board_id != ctx.board_id:
        raise Reject("not_found", "card not found")
    if card.deleted_at is None:
        raise Reject("validation", f"#{card.number} is not deleted", card_out(card))
    if card.parent_card_id is not None:
        parent = await db.scalar(select(Card.deleted_at).where(Card.id == card.parent_card_id))
        if parent is not None:
            raise Reject("gone", "its parent card was deleted")
    await ctx.undo_check(card.field_meta, ["deleted"], None)
    deleted_seq = card.field_meta.get("deleted", {}).get("seq")
    children = [
        c
        for c in (
            await db.scalars(
                select(Card)
                .where(Card.parent_card_id == card.id, Card.deleted_at.is_not(None))
                .with_for_update()
            )
        ).all()
        if c.field_meta.get("deleted", {}).get("seq") == deleted_seq
    ]
    seq, _ = await ctx.next_seq()
    # Keep the old key unless a live card took it meanwhile (keys never collide).
    scope = (
        _column(ctx.board_id, card.status_id)
        if card.parent_card_id is None
        else _siblings(card.parent_card_id)
    )
    taken = await db.scalar(select(Card.id).where(*scope, Card.position == card.position))
    if taken is not None:
        upper = await db.scalar(
            select(func.min(Card.position)).where(*scope, Card.position > card.position)
        )
        card.position = key_between(card.position, upper)
    for c in (card, *children):
        c.deleted_at = None
        c.updated_at = func.now()
        ctx.stamp(c, ["deleted"], seq)
    await db.flush()
    for c in (card, *children):
        await db.refresh(c)
    return {"_seq": seq, "card": card_out(card), "children": [card_out(c) for c in children]}


# --- statuses (columns) ------------------------------------------------------------------

_STATUS_FIELDS = ["name", "color", "position", "created"]


def _board_statuses(board_id: uuid.UUID, exclude: uuid.UUID | None = None):
    scope = (Status.board_id == board_id,)
    return (*scope, Status.id != exclude) if exclude else scope


async def _status(ctx: _Ctx, status_id: uuid.UUID) -> Status:
    status = await ctx.db.scalar(
        select(Status)
        .where(Status.id == status_id, Status.board_id == ctx.board_id)
        .with_for_update()
    )
    if status is None:
        raise Reject("gone", "that column no longer exists")
    return status


async def _name_taken(ctx: _Ctx, name: str, exclude: uuid.UUID | None = None) -> bool:
    """Names are unique per board, case-insensitively (CSV import matches them that way)."""
    found = await ctx.db.scalar(
        select(Status.id).where(
            *_board_statuses(ctx.board_id, exclude), func.lower(Status.name) == name.lower()
        )
    )
    return found is not None


async def _status_create(ctx: _Ctx, op: StatusCreate):
    """Also the undo of status.delete: it recreates the column with its old id."""
    d = op.data
    if await ctx.db.scalar(select(Status.id).where(Status.id == d.id)) is not None:
        raise Reject("validation", "column id already exists")
    if await _name_taken(ctx, d.name):
        raise Reject("validation", f"a column named {d.name!r} already exists")
    seq, _ = await ctx.next_seq()
    scope = _board_statuses(ctx.board_id)
    status = Status(
        id=d.id,
        board_id=ctx.board_id,
        name=d.name,
        color=d.color,
        position=await _key_in(ctx.db, Status, scope, d.after_id, d.before_id),
        field_meta={},
    )
    ctx.stamp(status, _STATUS_FIELDS, seq)
    ctx.db.add(status)
    await ctx.db.flush()
    return {"_seq": seq, "status": status_out(status)}


async def _status_update(ctx: _Ctx, op: StatusUpdate):
    """Rename / recolour: last write wins."""
    status = await _status(ctx, op.data.id)
    fields = op.data.model_dump(exclude_none=True, exclude={"id"})
    await ctx.undo_check(status.field_meta, list(fields), status_out(status))
    if "name" in fields and await _name_taken(ctx, fields["name"], exclude=status.id):
        raise Reject("validation", f"a column named {fields['name']!r} already exists")
    seq, _ = await ctx.next_seq()
    for name, value in fields.items():
        setattr(status, name, value)
    ctx.stamp(status, list(fields), seq)
    await ctx.db.flush()
    return {"_seq": seq, "status": status_out(status)}


async def _status_move(ctx: _Ctx, op: StatusMove):
    status = await _status(ctx, op.data.id)
    await ctx.undo_check(status.field_meta, ["position"], status_out(status))
    seq, _ = await ctx.next_seq()
    scope = _board_statuses(ctx.board_id, exclude=status.id)
    status.position = await _key_in(ctx.db, Status, scope, op.data.after_id, op.data.before_id)
    ctx.stamp(status, ["position"], seq)
    await ctx.db.flush()
    return {"_seq": seq, "status": status_out(status)}


async def _status_delete(ctx: _Ctx, op: StatusDelete):
    """Plan §2: rejected while the column has live cards. Its soft-deleted cards are purged
    in the same transaction (undoing their deletion then gets `gone`), so with ON DELETE
    RESTRICT nothing ever points at a missing column."""
    db = ctx.db
    status = await _status(ctx, op.data.id)
    await ctx.undo_check(status.field_meta, _STATUS_FIELDS, status_out(status))
    live = await db.scalar(select(func.count()).where(*_column(ctx.board_id, status.id)))
    if live:
        raise Reject("validation", f"column {status.name!r} is not empty", status_out(status))
    seq, _ = await ctx.next_seq()
    purged = (
        await db.scalars(
            delete(Card)
            .where(Card.board_id == ctx.board_id, Card.status_id == status.id)
            .returning(Card.id)
        )
    ).all()  # their children go with them (ON DELETE CASCADE)
    await db.delete(status)
    await db.flush()
    return {"_seq": seq, "id": str(status.id), "purged_ids": [str(i) for i in purged]}


# --- CSV import (plan §3.6) ----------------------------------------------------------------

# A board with no columns gets this one for top-level rows with an empty status.
DEFAULT_IMPORT_STATUS = "Todo"


async def apply_import(
    db: AsyncSession,
    member: Membership,
    client_id: uuid.UUID,
    parsed: Parsed,
    *,
    dry_run: bool = False,
    hub: Hub | None = None,
) -> dict:
    """Appends the parsed rows to the board in one transaction under the board lock: one
    seq, one `board.import` event (clients resync), all or nothing. A dry run does the
    same work and rolls back (the `I` preview): no seq, no event. Not undoable."""
    board_id = member.board.id
    async with board_lock(board_id):
        await _check_member(db, member, None)
        try:
            result, seq = await _import_rows(db, member, client_id, parsed)
        except BaseException:
            await db.rollback()
            raise
        if dry_run:
            await db.rollback()
            return {**result, "seq": None}
        data = {"created": result["created"], "statuses_created": result["statuses_created"]}
        await _commit_event(db, member, client_id, uuid7(), "board.import", seq, data, hub)
        return {**result, "seq": seq}


async def _import_rows(
    db: AsyncSession, member: Membership, client_id: uuid.UUID, parsed: Parsed
) -> tuple[dict, int]:
    board_id = member.board.id
    rows = parsed.rows
    statuses = (
        await db.scalars(
            select(Status).where(Status.board_id == board_id).order_by(Status.position, Status.id)
        )
    ).all()
    by_name = {s.name.lower(): s.id for s in statuses}

    # Columns: matched by name, case-insensitively; unknown names are appended right in
    # order of first appearance, each with the palette colour after the rightmost one's.
    new_statuses: list[Status] = []
    last_pos = statuses[-1].position if statuses else None
    last_color = statuses[-1].color if statuses else COLORS[-1]

    def column_of(name: str) -> uuid.UUID:
        nonlocal last_pos, last_color
        if not name:
            if statuses:
                return statuses[0].id
            name = DEFAULT_IMPORT_STATUS
        if (found := by_name.get(name.lower())) is not None:
            return found
        last_pos = key_between(last_pos, None)
        last_color = COLORS[(COLORS.index(last_color) + 1) % len(COLORS)]
        status = Status(
            id=uuid7(), board_id=board_id, name=name, color=last_color, position=last_pos
        )
        new_statuses.append(status)
        by_name[name.lower()] = status.id
        return status.id

    targets = [column_of(r.status) if r.parent is None else None for r in rows]

    # Numbers: the CSV ids as-is only on a board that never had a card (soft-deleted
    # cards keep their numbers), so a round-trip into a new board is identical.
    had_cards = await db.scalar(select(Card.id).where(Card.board_id == board_id).limit(1))
    keep = had_cards is None and parsed.numbers_keepable
    seq, first = await _next_seq(db, board_id, numbers=0 if keep else len(rows))
    numbers = [int(r.key or 0) for r in rows] if keep else [first + i for i in range(len(rows))]
    if keep and rows:
        await db.execute(
            update(Board)
            .where(Board.id == board_id)
            .values(next_number=func.greatest(Board.next_number, max(numbers) + 1))
        )

    # Positions: appended to the end of each column (live cards) and of each new parent's
    # children, in file order.
    ends = dict(
        (
            await db.execute(
                select(Card.status_id, func.max(Card.position))
                .where(
                    Card.board_id == board_id,
                    Card.parent_card_id.is_(None),
                    Card.deleted_at.is_(None),
                )
                .group_by(Card.status_id)
            )
        ).all()
    )
    ids = [uuid7() for _ in rows]
    stamp = {"seq": seq, "client": str(client_id)}
    meta = dict.fromkeys(_CREATED_FIELDS, stamp)
    top_level, children = [], []
    for i, r in enumerate(rows):
        scope = targets[i] if r.parent is None else ids[r.parent]
        ends[scope] = key_between(ends.get(scope), None)
        card = {
            "id": ids[i],
            "board_id": board_id,
            "number": numbers[i],
            "parent_card_id": None if r.parent is None else ids[r.parent],
            "status_id": targets[i],
            "position": ends[scope],
            "title": r.title,
            "description": r.description,
            "is_done": r.is_done,
            "tags": r.tags,
            "date": r.date,
            "field_meta": meta,
            "created_by": member.user.id,
        }
        (top_level if r.parent is None else children).append(card)

    status_meta = dict.fromkeys(_STATUS_FIELDS, stamp)
    for s in new_statuses:
        s.field_meta = status_meta
    db.add_all(new_statuses)
    await db.flush()
    for batch in (top_level, children):  # parents exist before their children
        if batch:
            await db.execute(insert(Card), batch)
    return {
        "created": len(rows),
        "statuses_created": [s.name for s in new_statuses],
        "numbers": "kept" if keep else "renumbered",
        "warnings": parsed.warnings,
    }, seq
