"""Real WebSocket tests (plan §6): the app runs in a uvicorn subprocess, clients are real
`websockets` connections with a session cookie from a real HTTP login.

`VWK_WS_PORT` fixes the server's port (CI scopes its netem delay to it); otherwise a free
port is picked."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from tests.api.helpers import add_board, add_member, add_user
from tests.api.ops_helpers import PW
from tests.conftest import BACKEND_DIR, PUBLIC_URL
from vwkanban.ids import uuid7

WAIT_S = 5.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Server:
    base: str  # http://127.0.0.1:<port>
    ws_base: str

    def client(self, **kw) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, headers={"Origin": PUBLIC_URL}, **kw)


@pytest.fixture(scope="session")
def server(database_url: str) -> Server:
    port = int(os.environ.get("VWK_WS_PORT") or _free_port())
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ADMIN_", "POSTGRES_", "ALLOW_SIGNUP", "COOKIE_"))
    }
    env |= {"DATABASE_URL": database_url, "PUBLIC_URL": PUBLIC_URL}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "vwkanban.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ws-max-size",
            "65536",
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get(f"{base}/api/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if proc.poll() is not None or time.monotonic() > deadline:
            proc.kill()
            raise RuntimeError("test server did not start")
        time.sleep(0.1)
    yield Server(base=base, ws_base=f"ws://127.0.0.1:{port}")
    proc.terminate()
    proc.wait(10)


@pytest.fixture(autouse=True)
async def clean_db(engine):
    # The server may still be finishing an op from the previous test (its client is gone),
    # and TRUNCATE can deadlock with it; Postgres then aborts the TRUNCATE, so retry.
    for attempt in range(10):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE users, boards CASCADE"))
            return
        except DBAPIError:
            if attempt == 9:
                raise
            await asyncio.sleep(0.1)


@dataclass
class WsClient:
    """A board socket that records every message. `expect` consumes messages in order of
    arrival, so the same message is never matched twice."""

    conn: ClientConnection
    client_id: uuid.UUID
    messages: list[dict] = field(default_factory=list)
    taken: set[int] = field(default_factory=set)
    arrived: asyncio.Condition = field(default_factory=asyncio.Condition)
    arrival_times: list[float] = field(default_factory=list)
    task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        try:
            async for raw in self.conn:
                msg = json.loads(raw)
                async with self.arrived:
                    self.messages.append(msg)
                    self.arrival_times.append(time.perf_counter())
                    self.arrived.notify_all()
        except ConnectionClosed:
            pass
        async with self.arrived:
            self.arrived.notify_all()

    async def expect(
        self,
        t: str | tuple[str, ...],
        pred: Callable[[dict], bool] = lambda m: True,
        *,
        consume: bool = True,
    ) -> dict:
        """The first unconsumed message of type `t` (or one of the types) matching `pred`,
        waiting up to WAIT_S for it. `consume=False` waits for any such message, consumed
        or not, and leaves it unconsumed."""
        types = (t,) if isinstance(t, str) else t

        def find():
            for i, m in enumerate(self.messages):
                if (not consume or i not in self.taken) and m.get("t") in types and pred(m):
                    if consume:
                        self.taken.add(i)
                    return m
            return None

        async with asyncio.timeout(WAIT_S):
            async with self.arrived:
                while (m := find()) is None:
                    if self.task is not None and self.task.done():
                        raise AssertionError(f"socket closed before a {t!r}: {self.messages}")
                    await self.arrived.wait()
                return m

    async def event_for(self, op_id) -> dict:
        return await self.expect("event", lambda m: m["op_id"] == str(op_id))

    async def answer(self, op_id) -> dict:
        """The ack or reject for `op_id`."""
        oid = str(op_id)
        return await self.expect(("ack", "reject"), lambda m: m.get("op_id") == oid)

    def events(self) -> list[dict]:
        return [m for m in self.messages if m["t"] == "event"]

    async def op(self, kind: str, data: dict, *, op_id=None, base_seq=0, undo=False) -> str:
        op_id = str(op_id or uuid7())
        await self.send(
            {
                "t": "op",
                "op_id": op_id,
                "kind": kind,
                "base_seq": base_seq,
                **({"undo": True} if undo else {}),
                "data": {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()},
            }
        )
        return op_id

    async def send(self, msg: dict) -> None:
        await self.conn.send(json.dumps(msg))

    async def closed(self) -> int | None:
        """Waits for the server to close the socket; returns the close code."""
        async with asyncio.timeout(WAIT_S):
            await self.conn.wait_closed()
        return self.conn.close_code

    async def close(self) -> None:
        await self.conn.close()
        if self.task:
            await self.task


@dataclass
class User:
    name: str
    id: uuid.UUID
    cookie: str
    http: httpx.AsyncClient


class Harness:
    def __init__(self, server: Server, engine) -> None:
        self.server = server
        self.engine = engine
        self._open: list[WsClient] = []
        self._http: list[httpx.AsyncClient] = []

    async def user(self, name: str) -> User:
        uid = await add_user(self.engine, name, PW)
        http = self.server.client()
        self._http.append(http)
        r = await http.post("/api/auth/login", json={"username": name, "password": PW})
        assert r.status_code == 200, r.text
        return User(name=name, id=uid, cookie=http.cookies["vwk_session"], http=http)

    async def board(self, owner: User, *members: User):
        board, statuses = await add_board(self.engine, owner.id, "Shared")
        for m in members:
            await add_member(self.engine, board, m.id, "editor")
        return board, statuses

    async def raw(
        self, board, cookie: str | None, origin: str | None = PUBLIC_URL
    ) -> ClientConnection:
        headers = {}
        if cookie:
            headers["Cookie"] = f"vwk_session={cookie}"
        if origin:
            headers["Origin"] = origin
        return await connect(
            f"{self.server.ws_base}/api/boards/{board}/ws",
            additional_headers=headers,
            max_size=None,
            proxy=None,
            compression=None,
        )

    async def connect(
        self, user: User, board, *, last_seq: int = 0, client_id=None, welcome=True
    ) -> WsClient:
        """A socket that has said hello (and, by default, received its welcome)."""
        c = WsClient(await self.raw(board, user.cookie), client_id or uuid7())
        self._open.append(c)
        c.start()
        await c.send({"t": "hello", "client_id": str(c.client_id), "last_seq": last_seq})
        if welcome:
            await c.expect("welcome")
        return c

    async def board_state(self, user: User, board) -> dict:
        r = await user.http.get(f"/api/boards/{board}")
        assert r.status_code == 200, r.text
        return r.json()

    async def aclose(self) -> None:
        for c in self._open:
            await c.close()
        for h in self._http:
            await h.aclose()


@pytest.fixture
async def ws(server, engine) -> AsyncIterator[Harness]:
    h = Harness(server, engine)
    yield h
    await h.aclose()
