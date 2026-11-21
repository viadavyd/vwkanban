"""The board WebSocket (plan §3.2): handshake, welcome and presence, fan-out, ack/reject,
replay and resync, closes on logout / board delete, rate and size limits."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.ops_helpers import op_body
from vwkanban.ids import uuid7
from vwkanban.sync.models import trim_events


def new_card(status, title="card", **extra) -> dict:
    return {"id": uuid7(), "status_id": status, "title": title, **extra}


# --- handshake ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "code"),
    [("no cookie", 4401), ("bad origin", 4400), ("no origin", 4400), ("stranger", 4403)],
)
async def test_handshake_rejects(ws, case, code):
    alice = await ws.user("alice")
    eve = await ws.user("eve")
    board, _ = await ws.board(alice)
    cookie, origin = alice.cookie, "http://vwk.test"
    if case == "no cookie":
        cookie = None
    elif case == "bad origin":
        origin = "http://evil.test"
    elif case == "no origin":
        origin = None
    elif case == "stranger":
        cookie = eve.cookie
    conn = await ws.raw(board, cookie, origin)
    await conn.wait_closed()
    assert conn.close_code == code


async def test_handshake_unknown_board(ws):
    alice = await ws.user("alice")
    for board in (uuid7(), "not-a-uuid"):
        conn = await ws.raw(board, alice.cookie)
        await conn.wait_closed()
        assert conn.close_code == 4404


async def test_handshake_expired_or_unknown_session(ws):
    alice = await ws.user("alice")
    board, _ = await ws.board(alice)
    conn = await ws.raw(board, "made-up-token")
    await conn.wait_closed()
    assert conn.close_code == 4401


async def test_first_message_must_be_hello(ws):
    alice = await ws.user("alice")
    board, _ = await ws.board(alice)
    conn = await ws.raw(board, alice.cookie)
    await conn.send('{"t": "ping"}')
    await conn.wait_closed()
    assert conn.close_code == 1008


# --- welcome, presence ------------------------------------------------------------------------


async def test_welcome_and_presence(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, _ = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    assert a.messages[0] == {
        "t": "welcome",
        "seq": 0,
        "presence": [{"user_id": str(alice.id), "username": "alice"}],
    }
    b = await ws.connect(bob, board)
    welcome = b.messages[0]
    assert [u["username"] for u in welcome["presence"]] == ["alice", "bob"]
    joined = await a.expect("presence")
    assert [u["username"] for u in joined["users"]] == ["alice", "bob"]

    # A second tab of bob's changes nobody's presence list.
    b2 = await ws.connect(bob, board)
    await b2.close()
    await b.close()
    left = await a.expect("presence")
    assert [u["username"] for u in left["users"]] == ["alice"]
    assert [m["t"] for m in a.messages].count("presence") == 2


async def test_ping_pong(ws):
    alice = await ws.user("alice")
    board, _ = await ws.board(alice)
    a = await ws.connect(alice, board)
    await a.send({"t": "ping"})
    await a.expect("pong")


# --- ops --------------------------------------------------------------------------------------


async def test_event_reaches_everyone_then_ack(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, (todo, *_) = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    a2 = await ws.connect(alice, board)  # alice's other tab
    b = await ws.connect(bob, board)
    op_id = await a.op("card.create", new_card(todo, "hello"))
    ack = await a.answer(op_id)
    assert ack == {"t": "ack", "op_id": op_id, "seq": 1}
    for c in (a, a2, b):
        ev = await c.event_for(op_id)
        assert ev["seq"] == 1
        assert ev["client_id"] == str(a.client_id)
        assert ev["actor"] == {"id": str(alice.id), "username": "alice"}
        assert ev["data"]["card"]["title"] == "hello"
        assert ev["data"]["card"]["number"] == 1
    # The sender's event comes before its ack.
    kinds = [m["t"] for m in a.messages if m.get("op_id") == op_id]
    assert kinds == ["event", "ack"]


async def test_reject_carries_code_message_current(ws):
    alice = await ws.user("alice")
    board, (todo, doing, _) = await ws.board(alice)
    a = await ws.connect(alice, board)
    created = await a.op("card.create", new_card(todo))
    card = (await a.event_for(created))["data"]["card"]
    deleted = await a.op("card.delete", {"id": card["id"]})
    await a.answer(deleted)
    moved = await a.op("card.move", {"id": card["id"], "status_id": doing})
    rej = await a.answer(moved)
    assert rej == {
        "t": "reject",
        "op_id": moved,
        "code": "gone",
        "message": "#1 was deleted by alice",
        "current": None,
    }
    # A reject consumes no seq: the next op gets 3.
    again = await a.op("card.create", new_card(todo))
    assert (await a.answer(again))["seq"] == 3


async def test_invalid_op_is_rejected_not_fatal(ws):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    bad = await a.op("card.create", {"id": uuid7(), "status_id": todo, "title": ""})
    rej = await a.answer(bad)
    assert rej["code"] == "validation" and rej["current"] is None
    good = await a.op("card.create", new_card(todo))
    assert (await a.answer(good))["t"] == "ack"


async def test_garbage_closes(ws):
    alice = await ws.user("alice")
    board, _ = await ws.board(alice)
    a = await ws.connect(alice, board)
    await a.conn.send("{not json")
    assert await a.closed() == 1003


async def test_rest_op_reaches_sockets(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, (todo, *_) = await ws.board(alice, bob)
    b = await ws.connect(bob, board)
    body = op_body("card.create", new_card(todo, "via REST"))
    r = await alice.http.post(f"/api/boards/{board}/ops", json=body)
    assert r.status_code == 200, r.text
    ev = await b.event_for(body["op"]["op_id"])
    assert ev["data"]["card"]["title"] == "via REST"


async def test_resend_same_op_id_gets_stored_ack_once(ws):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    data = new_card(todo)
    op_id = await a.op("card.create", data)
    first = await a.answer(op_id)
    await a.op("card.create", data, op_id=op_id)
    second = await a.answer(op_id)
    assert first == second
    assert len([e for e in a.events() if e["op_id"] == op_id]) == 1


# --- replay and resync ------------------------------------------------------------------


async def _make_events(c, status, n) -> list[str]:
    ids = [await c.op("card.create", new_card(status, f"c{i}")) for i in range(n)]
    for op_id in ids:
        await c.answer(op_id)
    return ids


async def test_reconnect_replays_missed_events(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, (todo, *_) = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    await _make_events(a, todo, 2)
    # bob loaded the board at seq 2, then alice wrote 3 more.
    missed = await _make_events(a, todo, 3)
    b = await ws.connect(bob, board, last_seq=2)
    assert b.messages[0]["seq"] == 5
    await b.event_for(missed[-1])
    assert [e["seq"] for e in b.events()] == [3, 4, 5]
    assert [e["op_id"] for e in b.events()] == missed
    # Live events follow the replay with no gap.
    live = await a.op("card.create", new_card(todo))
    assert (await b.event_for(live))["seq"] == 6


async def test_up_to_date_hello_gets_no_replay(ws):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    await _make_events(a, todo, 2)
    b = await ws.connect(alice, board, last_seq=2)
    await b.send({"t": "ping"})
    await b.expect("pong")
    assert [m["t"] for m in b.messages] == ["welcome", "pong"]


async def test_resync_after_trim(ws, engine):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    await _make_events(a, todo, 5)
    async with AsyncSession(engine) as db:
        await trim_events(db, keep=2)  # seqs 4 and 5 remain
    b = await ws.connect(alice, board, last_seq=2)
    await b.expect("resync")
    assert b.events() == []
    c = await ws.connect(alice, board, last_seq=3)  # 4 and 5 are enough
    await c.expect("event", lambda m: m["seq"] == 5)
    assert not any(m["t"] == "resync" for m in c.messages)


async def test_last_seq_ahead_of_board_resyncs(ws):
    alice = await ws.user("alice")
    board, _ = await ws.board(alice)
    b = await ws.connect(alice, board, last_seq=7)
    await b.expect("resync")


# --- closes ------------------------------------------------------------------------------


async def test_logout_closes_that_sessions_sockets(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, _ = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    b = await ws.connect(bob, board)
    r = await alice.http.post("/api/auth/logout")
    assert r.status_code == 204
    assert await a.closed() == 4401
    await b.expect("presence", lambda m: [u["username"] for u in m["users"]] == ["bob"])
    assert not b.conn.close_code


async def test_board_delete_closes_its_sockets(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, _ = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    b = await ws.connect(bob, board)
    r = await alice.http.delete(f"/api/boards/{board}")
    assert r.status_code == 204
    assert await a.closed() == 4404
    assert await b.closed() == 4404


async def test_op_flood_closes_4429(ws):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    await asyncio.gather(*(a.op("card.create", new_card(todo)) for _ in range(60)))
    assert await a.closed() == 4429


async def test_oversized_message_closes(ws):
    alice = await ws.user("alice")
    board, (todo, *_) = await ws.board(alice)
    a = await ws.connect(alice, board)
    await a.send({"t": "ping", "pad": "x" * 140_000})
    assert await a.closed() == 1009
