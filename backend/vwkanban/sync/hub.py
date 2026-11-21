"""In-memory fan-out per board (plan §1: one worker, so one process holds every socket).

Each socket gets an outbound queue drained by its own writer task, so `broadcast` never
awaits: `apply_op` calls it under the board lock, and a slow client can't stall the board.
A client that falls `OUTBOX_MAX` messages behind is closed (it reconnects and catches up
by replay or resync).
"""

import asyncio
import contextlib
import json
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

OUTBOX_MAX = 1000
CLOSE_TOO_SLOW = 1013  # "try again later"

_CLOSE = object()


class Conn:
    """One accepted board socket."""

    def __init__(
        self,
        ws: WebSocket,
        board_id: uuid.UUID,
        user_id: uuid.UUID,
        username: str,
        session: str,
        client_id: uuid.UUID,
    ) -> None:
        self.ws = ws
        self.board_id = board_id
        self.user_id = user_id
        self.username = username
        self.session = session  # sha256 of the session cookie (sessions.id)
        self.client_id = client_id
        self.closed = False
        self.close_code = 1000
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._writer = asyncio.create_task(self._write())

    def send(self, msg: dict) -> None:
        if self.closed:
            return
        if self._queue.qsize() >= OUTBOX_MAX:
            self.close(CLOSE_TOO_SLOW, drop_pending=True)
            return
        self._queue.put_nowait(msg)

    def close(self, code: int, *, drop_pending: bool = False) -> None:
        """Closes after the queued messages are sent (or at once with `drop_pending`)."""
        if self.closed:
            return
        self.closed = True
        self.close_code = code
        if drop_pending:
            while not self._queue.empty():
                self._queue.get_nowait()
        self._queue.put_nowait(_CLOSE)

    async def _write(self) -> None:
        try:
            while True:
                msg = await self._queue.get()
                if msg is _CLOSE:
                    await self.ws.close(self.close_code)
                    return
                await self.ws.send_text(json.dumps(msg, default=str))
        except Exception:
            # The peer went away mid-send (the error type depends on the ASGI server);
            # the handler's receive loop sees the disconnect and cleans up.
            return

    async def stop(self) -> None:
        """Ends the writer once the handler is done (lets a pending close frame go out)."""
        if not self._writer.done() and not self.closed:
            self._writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._writer


class Hub:
    def __init__(self) -> None:
        self._boards: defaultdict[uuid.UUID, set[Conn]] = defaultdict(set)

    def conns(self, board_id: uuid.UUID) -> list[Conn]:
        return list(self._boards.get(board_id, ()))

    def presence(self, board_id: uuid.UUID) -> list[dict]:
        """Users on the board, one entry per user however many tabs they have open."""
        users = {c.user_id: c.username for c in self._boards.get(board_id, ())}
        return [
            {"user_id": str(uid), "username": name}
            for uid, name in sorted(users.items(), key=lambda u: u[1])
        ]

    def add(self, conn: Conn) -> bool:
        """Registers `conn`; True if that brought a new user onto the board."""
        conns = self._boards[conn.board_id]
        new_user = all(c.user_id != conn.user_id for c in conns)
        conns.add(conn)
        return new_user

    def announce(self, board_id: uuid.UUID, exclude: Conn | None = None) -> None:
        msg = {"t": "presence", "users": self.presence(board_id)}
        for c in self.conns(board_id):
            if c is not exclude:
                c.send(msg)

    def leave(self, conn: Conn) -> None:
        conns = self._boards.get(conn.board_id)
        if conns is None or conn not in conns:
            return
        conns.discard(conn)
        if not conns:
            del self._boards[conn.board_id]
        elif all(c.user_id != conn.user_id for c in conns):
            self.announce(conn.board_id)

    def broadcast(self, board_id: uuid.UUID, msg: dict) -> None:
        for c in self.conns(board_id):
            c.send(msg)

    def _close(self, conns: list[Conn], code: int) -> None:
        for c in conns:
            self.leave(c)
            c.close(code)

    def close_board(self, board_id: uuid.UUID, code: int) -> None:
        self._close(self.conns(board_id), code)

    def close_user(self, board_id: uuid.UUID, user_id: uuid.UUID, code: int) -> None:
        self._close([c for c in self.conns(board_id) if c.user_id == user_id], code)

    def close_session(self, session: str, code: int) -> None:
        self._close(
            [c for conns in self._boards.values() for c in conns if c.session == session], code
        )
