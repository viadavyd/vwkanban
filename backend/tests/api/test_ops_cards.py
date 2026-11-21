"""M3b card ops through apply_op: card.move, card.restore, pasted children, and the undo
check (plan §3.2 "Undo ops"), single client unless noted."""

import uuid

import pytest
from sqlalchemy import text

from tests.api.helpers import add_board, add_card, add_user
from tests.api.ops_helpers import PW, column_titles, create, login_as, send
from vwkanban.ids import uuid7


@pytest.fixture
async def setup(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    board, statuses = await add_board(engine, alice, "B")
    async with make_client() as c:
        await login_as(c, "alice")
        yield c, board, statuses, alice


async def move(c, board, card, status, *, after=None, before=None, **kw):
    data = {"id": card["id"], "status_id": status}
    if after:
        data["after_id"] = after["id"]
    if before:
        data["before_id"] = before["id"]
    return await send(c, board, "card.move", data, **kw)


async def loaded(c, board) -> dict:
    return {x["id"]: x for x in (await c.get(f"/api/boards/{board}")).json()["cards"]}


# --- card.move ---------------------------------------------------------------------------


async def test_move_across_and_within_columns(setup):
    c, board, (todo, doing, _), _ = setup
    a, b, x = [await create(c, board, todo, t) for t in "abx"]
    y = await create(c, board, doing, "y")

    r = await move(c, board, x, doing, after=y)
    assert r.status_code == 200, r.text
    moved = r.json()["event"]["data"]["card"]
    assert moved["status_id"] == str(doing) and moved["number"] == x["number"]
    assert moved["field_meta"]["position"]["seq"] == r.json()["seq"]
    assert await column_titles(c, board, doing) == ["y", "x"]
    assert await column_titles(c, board, todo) == ["a", "b"]

    # Same column: b to the top (before a), then a to the end (no neighbours).
    assert (await move(c, board, b, todo, before=a)).status_code == 200
    assert await column_titles(c, board, todo) == ["b", "a"]
    assert (await move(c, board, b, todo, after=a)).status_code == 200
    assert await column_titles(c, board, todo) == ["a", "b"]
    assert (await move(c, board, a, todo)).status_code == 200
    assert await column_titles(c, board, todo) == ["b", "a"]


async def test_move_keeps_children_with_parent(setup, engine):
    c, board, (todo, doing, _), alice = setup
    parent = await create(c, board, todo, "parent")
    child = await add_card(engine, board, alice, number=50, parent_id=uuid.UUID(parent["id"]))
    assert (await move(c, board, parent, doing)).status_code == 200
    cards = await loaded(c, board)
    assert cards[str(child)]["parent_card_id"] == parent["id"]
    # A child can't be moved into a column by itself.
    r = await send(c, board, "card.move", {"id": child, "status_id": todo})
    assert r.status_code == 422


async def test_move_rejects(setup, engine):
    c, board, (todo, doing, _), alice = setup
    card = await create(c, board, todo)
    other, (foreign_status,) = await add_board(engine, alice, "Other", statuses=("Todo",))

    r = await move(c, board, card, foreign_status)
    assert r.status_code == 410 and r.json()["error"]["current"]["id"] == card["id"]
    r = await send(c, board, "card.move", {"id": uuid7(), "status_id": doing})
    assert r.status_code == 404

    assert (await send(c, board, "card.delete", {"id": card["id"]})).status_code == 200
    r = await move(c, board, card, doing)
    assert r.status_code == 410 and r.json()["error"]["code"] == "gone"


# --- paste (card.create with children) ---------------------------------------------------


async def test_paste_with_children_allocates_numbers_and_positions(setup, engine):
    c, board, (todo, *_), _ = setup
    first = await create(c, board, todo, "first")
    kids = [{"id": str(uuid7()), "title": f"kid {i}", "is_done": i == 0} for i in range(3)]
    r = await send(
        c,
        board,
        "card.create",
        {
            "id": uuid7(),
            "status_id": todo,
            "title": "copy",
            "after_id": first["id"],
            "children": kids,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["event"]["data"]
    assert data["card"]["number"] == 2
    children = data["children"]
    assert [x["number"] for x in children] == [3, 4, 5]
    assert [x["title"] for x in children] == ["kid 0", "kid 1", "kid 2"]
    assert all(
        x["parent_card_id"] == data["card"]["id"] and x["status_id"] is None for x in children
    )
    keys = [x["position"] for x in children]
    assert keys == sorted(keys, key=str.encode) and len(set(keys)) == 3
    assert children[0]["is_done"] is True
    async with engine.connect() as conn:
        nxt = (
            await conn.execute(text("SELECT next_number FROM boards WHERE id=:b"), {"b": board})
        ).scalar()
    assert nxt == 6
    assert len(await loaded(c, board)) == 5


@pytest.mark.parametrize("dup", ["parent", "sibling", "existing"])
async def test_paste_rejects_duplicate_ids(setup, dup):
    c, board, (todo, *_), _ = setup
    live = await create(c, board, todo)
    pid, kid = str(uuid7()), str(uuid7())
    second = {"parent": pid, "sibling": kid, "existing": live["id"]}[dup]
    data = {
        "id": pid,
        "status_id": todo,
        "title": "p",
        "children": [{"id": kid, "title": "a"}, {"id": second, "title": "b"}],
    }
    r = await send(c, board, "card.create", data)
    assert r.status_code == 422


async def test_paste_limits_children(setup):
    c, board, (todo, *_), _ = setup
    kids = [{"id": str(uuid7()), "title": "k"} for _ in range(101)]
    data = {"id": uuid7(), "status_id": todo, "title": "p", "children": kids}
    assert (await send(c, board, "card.create", data)).status_code == 422


# --- card.restore ------------------------------------------------------------------------


async def test_restore_brings_back_card_and_children_of_that_delete(setup, engine):
    c, board, (todo, *_), alice = setup
    a = await create(c, board, todo, "a")
    parent = await create(c, board, todo, "parent")
    b = await create(c, board, todo, "b")
    pid = uuid.UUID(parent["id"])
    kept = await add_card(engine, board, alice, number=50, parent_id=pid)
    earlier = await add_card(engine, board, alice, number=51, parent_id=pid)
    assert (await send(c, board, "card.delete", {"id": earlier})).status_code == 200
    r = await send(c, board, "card.delete", {"id": parent["id"]})
    seq = r.json()["seq"]

    r = await send(c, board, "card.restore", {"id": parent["id"]}, undo=True, base_seq=seq)
    assert r.status_code == 200, r.text
    data = r.json()["event"]["data"]
    assert data["card"]["position"] == parent["position"]  # its old key was free
    assert [x["id"] for x in data["children"]] == [str(kept)]
    assert data["card"]["field_meta"]["deleted"]["seq"] == r.json()["seq"]
    cards = await loaded(c, board)
    assert str(kept) in cards and str(earlier) not in cards
    assert await column_titles(c, board, todo) == ["a", "parent", "b"]
    assert a and b


async def test_restore_gets_a_new_key_if_its_old_one_was_taken(setup, engine):
    c, board, (todo, *_), _ = setup
    card = await create(c, board, todo, "x")
    end = await create(c, board, todo, "end")
    seq = (await send(c, board, "card.delete", {"id": card["id"]})).json()["seq"]
    # Another card lands on exactly the freed key (it is first in the column again).
    taker = await create(c, board, todo, "taker", before=end["id"])
    assert taker["position"] == card["position"]
    r = await send(c, board, "card.restore", {"id": card["id"]}, undo=True, base_seq=seq)
    assert r.status_code == 200
    pos = r.json()["event"]["data"]["card"]["position"]
    assert pos not in (taker["position"], end["position"])
    assert await column_titles(c, board, todo) == ["taker", "x", "end"]


async def test_restore_rejects(setup, engine):
    c, board, (todo, *_), alice = setup
    live = await create(c, board, todo)
    r = await send(c, board, "card.restore", {"id": live["id"]}, undo=True)
    assert r.status_code == 422 and r.json()["error"]["current"]["id"] == live["id"]
    r = await send(c, board, "card.restore", {"id": uuid7()}, undo=True)
    assert r.status_code == 410  # unknown = purged: nothing left to restore

    other, (ots,) = await add_board(engine, alice, "Other", statuses=("Todo",))
    foreign = await create(c, other, ots)
    await send(c, other, "card.delete", {"id": foreign["id"]})
    r = await send(c, board, "card.restore", {"id": foreign["id"]}, undo=True)
    assert r.status_code == 404


async def test_restore_child_needs_live_parent(setup, engine):
    c, board, (todo, *_), alice = setup
    parent = await create(c, board, todo, "parent")
    child = await add_card(engine, board, alice, number=50, parent_id=uuid.UUID(parent["id"]))
    seq = (await send(c, board, "card.delete", {"id": child})).json()["seq"]
    await send(c, board, "card.delete", {"id": parent["id"]})
    r = await send(c, board, "card.restore", {"id": child}, undo=True, base_seq=seq)
    assert r.status_code == 410


# --- undo check --------------------------------------------------------------------------


async def test_undo_check_reads_field_meta(setup, make_client):
    """An undo is rejected only if another client wrote a touched field after base_seq."""
    c, board, (todo, doing, _), _ = setup
    me, other = uuid7(), uuid7()
    card = await create(c, board, todo, client_id=me)
    r = await send(
        c, board, "card.update", {"id": card["id"], "fields": {"is_done": True}}, client_id=me
    )
    toggle_seq = r.json()["seq"]

    # The same client wrote again since: still allowed (no self-conflict).
    await send(
        c, board, "card.update", {"id": card["id"], "fields": {"is_done": True}}, client_id=me
    )
    # Another client writes a different field: allowed, the undo doesn't touch it.
    await move(c, board, card, doing, client_id=other)
    r = await send(
        c,
        board,
        "card.update",
        {"id": card["id"], "fields": {"is_done": False}},
        client_id=me,
        undo=True,
        base_seq=toggle_seq,
    )
    assert r.status_code == 200, r.text

    # Another client toggles after my move: undoing my move is still fine...
    move_seq = (await move(c, board, card, todo, client_id=me)).json()["seq"]
    await send(
        c, board, "card.update", {"id": card["id"], "fields": {"is_done": True}}, client_id=other
    )
    # ...but once it moves the card too, undoing my move would revert its move.
    await move(c, board, card, doing, client_id=other)
    r = await move(c, board, card, todo, client_id=me, undo=True, base_seq=move_seq)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "conflict" and err["message"] == "can't undo: changed by alice"
    assert err["current"]["status_id"] == str(doing)
    # Without undo the same move is plain LWW.
    assert (await move(c, board, card, todo, client_id=me)).status_code == 200


async def test_undo_of_create_deletes(setup):
    c, board, (todo, *_), _ = setup
    me = uuid7()
    r = await send(
        c, board, "card.create", {"id": uuid7(), "status_id": todo, "title": "x"}, client_id=me
    )
    card, seq = r.json()["event"]["data"]["card"], r.json()["seq"]
    r = await send(
        c, board, "card.delete", {"id": card["id"]}, client_id=me, undo=True, base_seq=seq
    )
    assert r.status_code == 200
    assert await loaded(c, board) == {}
