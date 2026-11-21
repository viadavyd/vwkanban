"""Multi-client op tests over POST /ops (plan §3.5 rows that need no WebSocket or card mode).
Two users on one board, each with its own client_id; requests run concurrently."""

import asyncio

import pytest

from tests.api.helpers import add_board, add_member, add_user
from tests.api.ops_helpers import PW, column_titles, create, login_as, send
from vwkanban.ids import uuid7


@pytest.fixture
async def two(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    bob = await add_user(engine, "bob", PW)
    board, statuses = await add_board(engine, alice, "Shared")
    await add_member(engine, board, bob, "editor")
    async with make_client() as a, make_client() as b:
        await login_as(a, "alice")
        await login_as(b, "bob")
        yield a, b, board, statuses


async def snapshot(c, board):
    d = (await c.get(f"/api/boards/{board}")).json()
    return d["seq"], sorted(
        (x["id"], x["status_id"], x["position"], x["is_done"]) for x in d["cards"]
    )


async def test_insert_after_same_card_both_survive(two):
    a, b, board, (todo, *_) = two
    x = await create(a, board, todo, "x")
    await create(a, board, todo, "y")
    ra, rb = await asyncio.gather(
        send(
            a,
            board,
            "card.create",
            {"id": uuid7(), "status_id": todo, "title": "A", "after_id": x["id"]},
        ),
        send(
            b,
            board,
            "card.create",
            {"id": uuid7(), "status_id": todo, "title": "B", "after_id": x["id"]},
        ),
    )
    assert ra.status_code == rb.status_code == 200
    ka = ra.json()["event"]["data"]["card"]["position"]
    kb = rb.json()["event"]["data"]["card"]["position"]
    assert ka != kb
    assert sorted([ra.json()["seq"], rb.json()["seq"]]) == [3, 4]  # distinct, gap-free
    titles = await column_titles(a, board, todo)
    assert titles[0] == "x" and titles[-1] == "y" and sorted(titles[1:3]) == ["A", "B"]
    # Numbers are distinct too, and both clients see the same board.
    assert await snapshot(a, board) == await snapshot(b, board)


async def test_insert_after_card_deleted_by_other(two):
    a, b, board, (todo, *_) = two
    first = await create(a, board, todo, "first")
    seven = await create(a, board, todo, "seven")
    last = await create(a, board, todo, "last")
    assert (await send(b, board, "card.delete", {"id": seven["id"]})).status_code == 200
    # A still has the old view: inserts after #seven, before "last" → server uses before_id.
    await create(a, board, todo, "new", after=seven["id"], before=last["id"])
    assert await column_titles(b, board, todo) == ["first", "new", "last"]
    # Neither neighbour live → end of column.
    assert (await send(b, board, "card.delete", {"id": last["id"]})).status_code == 200
    await create(a, board, todo, "end", after=seven["id"], before=last["id"])
    assert await column_titles(b, board, todo) == ["first", "new", "end"]
    assert first["number"] == 1


async def test_toggle_after_other_deleted(two):
    a, b, board, (todo, *_) = two
    card = await create(a, board, todo)
    assert (await send(b, board, "card.delete", {"id": card["id"]})).status_code == 200
    r = await send(a, board, "card.update", {"id": card["id"], "fields": {"is_done": True}})
    assert r.status_code == 410
    assert r.json()["error"]["current"] is None


async def test_concurrent_toggles_last_write_wins(two):
    a, b, board, (todo, *_) = two
    card = await create(a, board, todo)
    ra, rb = await asyncio.gather(
        send(a, board, "card.update", {"id": card["id"], "fields": {"is_done": True}}),
        send(b, board, "card.update", {"id": card["id"], "fields": {"is_done": False}}),
    )
    last = max((ra.json(), rb.json()), key=lambda r: r["seq"])
    final = last["event"]["data"]["card"]["is_done"]
    assert (await a.get(f"/api/boards/{board}")).json()["cards"][0]["is_done"] is final
    assert await snapshot(a, board) == await snapshot(b, board)


async def test_op_storm_converges(two):
    """Two clients fire mixed ops at once; seqs are gap-free and both views agree."""
    a, b, board, (todo, doing, _) = two

    async def run(c, status):
        ids = []
        for i in range(15):
            card = await create(c, board, status, f"c{i}", after=ids[-1] if ids else None)
            ids.append(card["id"])
            if i % 3 == 0:
                await send(c, board, "card.update", {"id": card["id"], "fields": {"is_done": True}})
            if i % 5 == 4:
                await send(c, board, "card.delete", {"id": ids[0]})
                ids.pop(0)

    await asyncio.gather(run(a, todo), run(b, todo), run(a, doing))
    seq, cards = await snapshot(a, board)
    assert (seq, cards) == await snapshot(b, board)
    assert seq == 3 * (15 + 5 + 3)
    # No position collisions within a column.
    assert len({(s, p) for _, s, p, _ in cards}) == len(cards)
