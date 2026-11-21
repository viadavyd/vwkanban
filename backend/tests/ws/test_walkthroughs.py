"""Plan §3.5 concurrency walk-throughs, one test per row that needs no card mode (the
text-field rows arrive with M5). Every test uses two real sockets, A (alice) and B (bob),
and ends with both sockets' event streams and a fresh GET agreeing."""

import asyncio

import pytest

from tests.api.ops_helpers import op_body
from tests.ws.test_ws import new_card
from vwkanban.ids import uuid7


@pytest.fixture
async def ab(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, statuses = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    b = await ws.connect(bob, board)
    return ws, alice, bob, board, statuses, a, b


async def ok(c, kind, data, **kw) -> dict:
    """Sends an op and returns its event (asserts it was acked)."""
    op_id = await c.op(kind, data, **kw)
    ans = await c.answer(op_id)
    assert ans["t"] == "ack", ans
    return await c.event_for(op_id)


async def converged(ws, user, board, *clients) -> dict:
    """Every client saw the same events, in seq order with no gap, up to the board's seq;
    folding them gives the board a fresh GET returns."""
    state = await ws.board_state(user, board)
    for c in clients:
        await c.expect("event", lambda m: m["seq"] == state["seq"], consume=False)
    # A socket that joined later starts later; where streams overlap they agree.
    by_seq: dict[int, str] = {}
    for c in clients:
        seqs = [e["seq"] for e in c.events()]
        assert seqs == list(range(seqs[0], state["seq"] + 1))
        for e in c.events():
            assert by_seq.setdefault(e["seq"], e["op_id"]) == e["op_id"]
    full = next(c for c in clients if c.events()[0]["seq"] == 1)
    live = fold(full.events())
    assert live == {c["id"]: (c["status_id"], c["position"], c["is_done"]) for c in state["cards"]}
    return state


def fold(events) -> dict:
    cards: dict = {}
    for e in events:
        d = e["data"]
        for c in [d.get("card"), *(d.get("children") or [])]:
            if c:
                cards[c["id"]] = (c["status_id"], c["position"], c["is_done"])
        for i in d.get("deleted_ids", []) + d.get("purged_ids", []):
            cards.pop(i, None)
    return cards


def column(state, status) -> list[str]:
    col = [c for c in state["cards"] if c["status_id"] == str(status)]
    return [c["title"] for c in sorted(col, key=lambda c: c["position"].encode())]


async def test_both_move_the_same_card_at_once(ab):
    """Row 1: applied in seq order, last wins, both converge on the final event."""
    ws, alice, _, board, (todo, doing, done), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    oa, ob = await asyncio.gather(
        a.op("card.move", {"id": card["id"], "status_id": doing}),
        b.op("card.move", {"id": card["id"], "status_id": done}),
    )
    acks = [await a.answer(oa), await b.answer(ob)]
    assert [x["t"] for x in acks] == ["ack", "ack"]
    last = oa if acks[0]["seq"] > acks[1]["seq"] else ob
    final = (await a.event_for(last))["data"]["card"]["status_id"]
    assert (await b.event_for(last))["data"]["card"]["status_id"] == final
    state = await converged(ws, alice, board, a, b)
    assert state["cards"][0]["status_id"] == final


async def test_both_insert_after_the_same_card(ab):
    """Row 2: distinct keys in seq order; both survive in the same order everywhere."""
    ws, alice, _, board, (todo, *_), a, b = ab
    x = (await ok(a, "card.create", new_card(todo, "x")))["data"]["card"]
    await ok(a, "card.create", new_card(todo, "y"))
    oa, ob = await asyncio.gather(
        a.op("card.create", new_card(todo, "A", after_id=x["id"])),
        b.op("card.create", new_card(todo, "B", after_id=x["id"])),
    )
    ea, eb = await a.event_for(oa), await a.event_for(ob)
    assert ea["data"]["card"]["position"] != eb["data"]["card"]["position"]
    assert ea["data"]["card"]["number"] != eb["data"]["card"]["number"]
    state = await converged(ws, alice, board, a, b)
    titles = column(state, todo)
    assert titles[0] == "x" and titles[-1] == "y" and sorted(titles[1:3]) == ["A", "B"]


async def test_move_after_other_deleted_is_gone(ab):
    """Row 8: A's move of a card B deleted is `gone`, naming B (the client toasts it and
    clears its register)."""
    ws, alice, _, board, (todo, doing, _), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    await ok(b, "card.delete", {"id": card["id"]})
    await a.expect("event", lambda m: m["kind"] == "card.delete")
    rej = await a.answer(await a.op("card.move", {"id": card["id"], "status_id": doing}))
    assert rej["t"] == "reject" and rej["code"] == "gone"
    assert rej["message"] == "#1 was deleted by bob"
    state = await converged(ws, alice, board, a, b)
    assert state["cards"] == []


async def test_move_into_column_while_other_deletes_it(ab):
    """Row 11: whichever commits first wins: the delete is refused (column not empty) or
    the move is `gone`."""
    ws, alice, _, board, (todo, doing, _), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    oa, ob = await asyncio.gather(
        a.op("card.move", {"id": card["id"], "status_id": doing}),
        b.op("status.delete", {"id": doing}),
    )
    ra, rb = await a.answer(oa), await b.answer(ob)
    if ra["t"] == "ack":
        assert rb["t"] == "reject" and rb["code"] == "validation"
    else:
        assert ra["code"] == "gone" and rb["t"] == "ack"
    state = await converged(ws, alice, board, a, b)
    assert [s["id"] for s in state["statuses"]].count(str(doing)) == (ra["t"] == "ack")


@pytest.mark.parametrize("with_before", [True, False])
async def test_insert_after_card_other_moved_away(ab, with_before):
    """Row 12: the neighbour left the target list → the server uses `before_id`, else the
    end of the column."""
    ws, alice, _, board, (todo, doing, _), a, b = ab
    await ok(a, "card.create", new_card(todo, "first"))
    seven = (await ok(a, "card.create", new_card(todo, "seven")))["data"]["card"]
    last = (await ok(a, "card.create", new_card(todo, "last")))["data"]["card"]
    await ok(b, "card.move", {"id": seven["id"], "status_id": doing})
    # A's view is stale: it still has #seven between first and last.
    at = {"after_id": seven["id"], **({"before_id": last["id"]} if with_before else {})}
    await ok(a, "card.create", new_card(todo, "new", **at))
    state = await converged(ws, alice, board, a, b)
    expected = ["first", "new", "last"] if with_before else ["first", "last", "new"]
    assert column(state, todo) == expected
    assert column(state, doing) == ["seven"]


async def test_undo_after_other_moved_the_card_is_conflict(ab):
    """Row 13: undo touches `position`, which B wrote after A's op → conflict."""
    ws, alice, _, board, (todo, doing, done), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    moved = await ok(a, "card.move", {"id": card["id"], "status_id": doing})
    await ok(b, "card.move", {"id": card["id"], "status_id": done})
    undo = await a.op(
        "card.move",
        {"id": card["id"], "status_id": todo},
        undo=True,
        base_seq=moved["seq"],
    )
    rej = await a.answer(undo)
    assert rej["t"] == "reject" and rej["code"] == "conflict"
    assert rej["message"] == "can't undo: changed by bob"
    assert rej["current"]["status_id"] == str(done)
    state = await converged(ws, alice, board, a, b)
    assert state["cards"][0]["status_id"] == str(done)


async def test_near_simultaneous_commits_broadcast_in_seq_order(ab):
    """Row 14: many concurrent ops from both: every socket gets one gap-free stream in seq
    order (the per-board lock keeps broadcast order = commit order)."""
    ws, alice, _, board, (todo, doing, _), a, b = ab
    sends = [a.op("card.create", new_card(todo, f"a{i}")) for i in range(20)]
    sends += [b.op("card.create", new_card(doing, f"b{i}")) for i in range(20)]
    op_ids = await asyncio.gather(*sends)
    for c, ids in ((a, op_ids[:20]), (b, op_ids[20:])):
        for op_id in ids:
            assert (await c.answer(op_id))["t"] == "ack"
    state = await converged(ws, alice, board, a, b)
    assert state["seq"] == 40
    assert [e["seq"] for e in a.events()] == list(range(1, 41))


async def test_offline_ops_then_reconnect(ab):
    """Row 15: A goes offline, B keeps working; A queued 4 ops (its first one had reached
    the server before the drop). On reconnect A gets the missed events, then re-sends its
    queue with the original op_ids: no duplicates, everything converges."""
    ws, alice, _, board, (todo, doing, _), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    sent_before_drop = new_card(todo, "q0")
    first_op = await a.op("card.create", sent_before_drop)
    await a.answer(first_op)
    last_seen = max(e["seq"] for e in a.events())
    await a.close()

    for i in range(3):
        await ok(b, "card.create", new_card(doing, f"b{i}"))
    queued = [
        ("card.create", sent_before_drop, first_op),
        ("card.create", new_card(todo, "q1"), str(uuid7())),
        ("card.update", {"id": card["id"], "fields": {"is_done": True}}, str(uuid7())),
        ("card.move", {"id": card["id"], "status_id": doing}, str(uuid7())),
    ]

    a2 = await ws.connect(alice, board, last_seq=last_seen, client_id=a.client_id)
    replay = [await a2.expect("event") for _ in range(3)]
    assert [e["data"]["card"]["title"] for e in replay] == ["b0", "b1", "b2"]
    for kind, data, op_id in queued:
        await a2.op(kind, data, op_id=op_id)
    answers = [await a2.answer(op_id) for *_, op_id in queued]
    assert [x["t"] for x in answers] == ["ack"] * 4
    assert answers[0]["seq"] == last_seen  # the stored ack: not applied twice
    state = await converged(ws, alice, board, a2, b)
    titles = sorted(c["title"] for c in state["cards"])
    assert titles == ["5", "b0", "b1", "b2", "q0", "q1"]
    five = next(c for c in state["cards"] if c["title"] == "5")
    assert five["is_done"] and five["status_id"] == str(doing)


async def test_same_op_sent_twice(ab):
    """Row 16: a resend (WS twice, then POST) hits the op_id → same ack, no double card."""
    ws, alice, _, board, (todo, *_), a, b = ab
    data = new_card(todo, "once")
    op_id = await a.op("card.create", data)
    await a.op("card.create", data, op_id=op_id)
    first = await a.answer(op_id)
    second = await a.answer(op_id)
    assert first == second == {"t": "ack", "op_id": op_id, "seq": 1}
    r = await alice.http.post(
        f"/api/boards/{board}/ops", json=op_body("card.create", data, op_id=op_id)
    )
    assert r.status_code == 200 and r.json()["seq"] == 1
    state = await converged(ws, alice, board, a, b)
    assert [c["title"] for c in state["cards"]] == ["once"]
    assert len(b.events()) == 1
