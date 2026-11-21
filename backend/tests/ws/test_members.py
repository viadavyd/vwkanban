"""Removing a member disconnects them (plan §3.1, M4 accept)."""

from tests.ws.test_ws import new_card


async def test_removed_member_is_disconnected_and_refused(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, (todo, *_) = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    b = await ws.connect(bob, board)
    b2 = await ws.connect(bob, board)  # every tab of bob's goes
    await a.expect("presence")

    r = await alice.http.delete(f"/api/boards/{board}/members/{bob.id}")
    assert r.status_code == 204
    assert await b.closed() == 4403
    assert await b2.closed() == 4403
    left = await a.expect("presence", lambda m: [u["username"] for u in m["users"]] == ["alice"])
    assert left

    again = await ws.raw(board, bob.cookie)
    await again.wait_closed()
    assert again.close_code == 4403

    # alice's socket is unaffected.
    op = await a.op("card.create", new_card(todo))
    assert (await a.answer(op))["t"] == "ack"
