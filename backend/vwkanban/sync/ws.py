"""Board WebSocket `/api/boards/{id}/ws` (plan §3.2).

Handshake: Origin (4400), session cookie (4401), board (4404) and membership (4403) are
checked before the socket is registered or sent anything. Browsers can't read the status
of a refused upgrade, so a failed check accepts and closes at once with its code.

Then the client sends `hello{client_id, last_seq}`. Under the board's op lock the server
registers the socket and sends `welcome{seq, presence}` followed by the missed events
(or `resync` when they're no longer in the log), so live events follow with no gap.
`op`s go through `apply_op`, the same path as `POST /ops`: the event is broadcast to the
board, then the sender gets `ack{op_id, seq}` or `reject{op_id, code, message, current}`.

A reader task timestamps arrivals for the rate limit (over 50 ops/s → 4429) while ops are
applied one at a time, in order, by the handler.
"""

import asyncio
import contextlib
import json
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import select

from vwkanban.auth.origin import origin_allowed
from vwkanban.auth.sessions import COOKIE_NAME, hash_token, resolve_session
from vwkanban.boards.deps import Membership, load_membership
from vwkanban.boards.models import Board
from vwkanban.errors import ApiError
from vwkanban.sync.hub import Conn, Hub
from vwkanban.sync.models import BoardEvent
from vwkanban.sync.ops import apply_op, board_lock
from vwkanban.sync.schemas import Op

router = APIRouter()

CLOSE_BAD_ORIGIN = 4400
CLOSE_NO_SESSION = 4401
CLOSE_NOT_MEMBER = 4403
CLOSE_BOARD_GONE = 4404
CLOSE_RATE = 4429
CLOSE_PROTOCOL = 1008
CLOSE_UNSUPPORTED = 1003

HELLO_TIMEOUT_S = 10
OPS_PER_SECOND = 50
INBOX_MAX = 200

_op_adapter: TypeAdapter[Op] = TypeAdapter(Op)


class Hello(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: str = Field(pattern="^hello$")
    client_id: uuid.UUID
    last_seq: int = Field(ge=0)


class _Bucket:
    """Token bucket: `rate` ops per second, bursts up to `rate`."""

    def __init__(self, rate: int) -> None:
        self.rate = rate
        self.tokens = float(rate)
        self.at = time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.rate, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    field = ".".join(str(p) for p in err.get("loc", ()))
    msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
    return f"{field}: {msg}" if field else msg


async def _handshake(ws: WebSocket, raw_board_id: str) -> tuple[int, Membership | None, str]:
    """(close code or 0, membership, session hash)."""
    settings = ws.app.state.settings
    if not origin_allowed(ws.headers.get("origin"), settings.public_origin):
        return CLOSE_BAD_ORIGIN, None, ""
    token = ws.cookies.get(COOKIE_NAME)
    async with ws.app.state.sessionmaker() as db:
        resolved = await resolve_session(db, token) if token else None
        if resolved is None:
            return CLOSE_NO_SESSION, None, ""
        user, _ = resolved
        try:
            board_id = uuid.UUID(raw_board_id)
        except ValueError:
            return CLOSE_BOARD_GONE, None, ""
        if await db.scalar(select(Board.id).where(Board.id == board_id)) is None:
            return CLOSE_BOARD_GONE, None, ""
        member = await load_membership(db, board_id, user)
        if member is None:
            return CLOSE_NOT_MEMBER, None, ""
        return 0, member, hash_token(token)


async def _welcome(ws: WebSocket, hub: Hub, conn: Conn, member: Membership, last_seq: int) -> int:
    """Registers `conn` and sends welcome + replay (or resync). Returns a close code if the
    board or the membership went away since the handshake, else 0."""
    board_id = conn.board_id
    async with board_lock(board_id):  # no op commits between the log read and registering
        async with ws.app.state.sessionmaker() as db:
            seq = await db.scalar(select(Board.seq).where(Board.id == board_id))
            if seq is None:
                return CLOSE_BOARD_GONE
            if await load_membership(db, board_id, member.user) is None:
                return CLOSE_NOT_MEMBER
            replay: list[dict] | None = []
            if last_seq > seq:
                replay = None
            elif 0 < last_seq < seq:
                rows = (
                    await db.scalars(
                        select(BoardEvent.payload)
                        .where(BoardEvent.board_id == board_id, BoardEvent.seq > last_seq)
                        .order_by(BoardEvent.seq)
                    )
                ).all()
                replay = list(rows) if len(rows) == seq - last_seq else None  # trimmed
        new_user = hub.add(conn)
        conn.send({"t": "welcome", "seq": seq, "presence": hub.presence(board_id)})
        if replay is None:
            conn.send({"t": "resync"})
        for event in replay or ():
            conn.send({"t": "event", **event})
        if new_user:
            hub.announce(board_id, exclude=conn)
    return 0


async def _handle(ws: WebSocket, hub: Hub, conn: Conn, member: Membership, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except ValueError:
        return conn.close(CLOSE_UNSUPPORTED)
    t = msg.get("t") if isinstance(msg, dict) else None
    if t == "ping":
        return conn.send({"t": "pong"})
    if t != "op":
        return conn.close(CLOSE_PROTOCOL)
    body = {k: v for k, v in msg.items() if k != "t"}
    try:
        op = _op_adapter.validate_python(body)
    except ValidationError as e:
        try:
            op_id = str(uuid.UUID(str(body.get("op_id"))))
        except ValueError:
            return conn.close(CLOSE_PROTOCOL)
        return conn.send(
            {
                "t": "reject",
                "op_id": op_id,
                "code": "validation",
                "message": _first_error(e),
                "current": None,
            }
        )
    async with ws.app.state.sessionmaker() as db:
        try:
            ack = await apply_op(db, member, conn.client_id, op, hub)
        except ApiError as e:
            conn.send(
                {
                    "t": "reject",
                    "op_id": str(op.op_id),
                    "code": e.code,
                    "message": e.detail,
                    "current": e.extra.get("current"),
                }
            )
        else:
            conn.send({"t": "ack", "op_id": str(op.op_id), "seq": ack.seq})


async def _read(ws: WebSocket, conn: Conn, inbox: asyncio.Queue[str | None]) -> None:
    """Receives until the peer goes away; enforces the op rate as messages arrive."""
    bucket = _Bucket(OPS_PER_SECOND)
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                conn.close(CLOSE_UNSUPPORTED)
                continue
            if conn.closed:
                continue  # closing: drain until the peer's close arrives
            if not bucket.take() or inbox.qsize() >= INBOX_MAX:
                conn.close(CLOSE_RATE)
                continue
            inbox.put_nowait(text)
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        inbox.put_nowait(None)


@router.websocket("/api/boards/{board_id}/ws")
async def board_ws(ws: WebSocket, board_id: str) -> None:
    hub: Hub = ws.app.state.hub
    code, member, session = await _handshake(ws, board_id)
    await ws.accept()
    if code or member is None:
        await ws.close(code)
        return
    try:
        async with asyncio.timeout(HELLO_TIMEOUT_S):
            hello = Hello.model_validate_json(await ws.receive_text())
    except (TimeoutError, ValidationError, KeyError):
        await ws.close(CLOSE_PROTOCOL)
        return
    except (WebSocketDisconnect, RuntimeError):
        return

    conn = Conn(ws, member.board.id, member.user.id, member.user.username, session, hello.client_id)
    inbox: asyncio.Queue[str | None] = asyncio.Queue(INBOX_MAX + 1)
    reader: asyncio.Task | None = None
    try:
        if code := await _welcome(ws, hub, conn, member, hello.last_seq):
            conn.close(code)
            return
        reader = asyncio.create_task(_read(ws, conn, inbox))
        while (raw := await inbox.get()) is not None:
            if not conn.closed:
                await _handle(ws, hub, conn, member, raw)
    finally:
        hub.leave(conn)
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        await conn.stop()
