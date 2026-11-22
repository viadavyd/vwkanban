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


# --- text fields (M5) ----------------------------------------------------------------------


async def update(c, board, card, base_seq=None, **fields):
    """card.update from a fresh client; by default its base is the board's current seq
    (as if the field had just been opened)."""
    if base_seq is None:
        base_seq = (await c.get(f"/api/boards/{board}")).json()["seq"]
    return await send(
        c, board, "card.update", {"id": card["id"], "fields": fields}, base_seq=base_seq
    )


async def test_text_fields_are_written_and_stamped(setup):
    c, board, (todo, *_), _ = setup
    card = await create(c, board, todo, "old")
    r = await update(
        c,
        board,
        card,
        title="  new  ",
        description='line 1\nline 2, "quoted"',
        tags=["ui", "bug"],
        date="2026-11-30",
    )
    assert r.status_code == 200, r.text
    out = r.json()["event"]["data"]["card"]
    assert out["title"] == "new"  # stripped
    assert out["description"] == 'line 1\nline 2, "quoted"'
    assert out["tags"] == ["ui", "bug"] and out["date"] == "2026-11-30"
    for f in ("title", "description", "tags", "date"):
        assert out["field_meta"][f]["seq"] == r.json()["seq"]
    assert out["field_meta"]["is_done"]["seq"] < r.json()["seq"]  # untouched

    # date: null clears the due date; a field not sent is left alone.
    out = (await update(c, board, card, date=None)).json()["event"]["data"]["card"]
    assert out["date"] is None and out["tags"] == ["ui", "bug"]
    assert (await loaded(c, board))[card["id"]]["description"] == 'line 1\nline 2, "quoted"'


async def test_due_date_takes_an_optional_time(setup):
    """The due date is `YYYY-MM-DD[ HH:MM]` (wall clock); a `T` separator is normalised."""
    c, board, (todo, *_), _ = setup
    card = await create(c, board, todo, "due")
    out = (await update(c, board, card, date="2026-11-30T14:30")).json()["event"]["data"]["card"]
    assert out["date"] == "2026-11-30 14:30"
    assert (await loaded(c, board))[card["id"]]["date"] == "2026-11-30 14:30"
    # A date without a time drops the time; null clears both.
    out = (await update(c, board, card, date="2026-12-01")).json()["event"]["data"]["card"]
    assert out["date"] == "2026-12-01"
    await update(c, board, card, date="2026-12-02 08:00")
    assert (await update(c, board, card, date=None)).json()["event"]["data"]["card"]["date"] is None
    for bad in ("2026-11-30 24:00", "2026-11-30 9:00", "2026-11-30 12:00:00", "noon"):
        assert (await update(c, board, card, date=bad)).status_code == 422, bad
    new = {"id": str(uuid7()), "status_id": todo, "title": "t", "date": "2027-01-01 07:05"}
    r = await send(c, board, "card.create", new)
    assert r.json()["event"]["data"]["card"]["date"] == "2027-01-01 07:05"


async def test_text_conflict_against_base_seq(setup):
    """Plan §3.2: `conflict` if field_meta[f].seq > base_seq and another client wrote it;
    the reject carries the card's current state and consumes no seq."""
    c, board, (todo, *_), _ = setup
    me, other = uuid7(), uuid7()
    card = await create(c, board, todo, client_id=me)
    base = (await c.get(f"/api/boards/{board}")).json()["seq"]
    data = {"id": card["id"], "fields": {"description": "theirs"}}
    seq = (await send(c, board, "card.update", data, client_id=other, base_seq=base)).json()["seq"]

    mine = {"id": card["id"], "fields": {"description": "mine"}}
    r = await send(c, board, "card.update", mine, client_id=me, base_seq=base)
    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["code"] == "conflict"
    assert err["message"] == f"#{card['number']}'s description was changed by alice"
    assert err["current"]["description"] == "theirs"
    assert (await c.get(f"/api/boards/{board}")).json()["seq"] == seq  # no seq consumed

    # A different field, or is_done (LWW), is fine with the same stale base.
    other_field = {"id": card["id"], "fields": {"title": "t", "is_done": True}}
    r = await send(c, board, "card.update", other_field, client_id=me, base_seq=base)
    assert r.status_code == 200, r.text
    # `:w!`: the same write with the current seq as base wins.
    r = await send(c, board, "card.update", mine, client_id=me, base_seq=seq)
    assert r.status_code == 200, r.text
    assert r.json()["event"]["data"]["card"]["description"] == "mine"


async def test_text_update_of_a_deleted_card_is_gone(setup):
    c, board, (todo, *_), _ = setup
    card = await create(c, board, todo, "5")
    await send(c, board, "card.delete", {"id": card["id"]})
    r = await update(c, board, card, description="draft")
    assert r.status_code == 410
    assert r.json()["error"]["message"] == f"#{card['number']} was deleted by alice"


async def test_undo_of_a_text_update(setup):
    c, board, (todo, *_), _ = setup
    me, other = uuid7(), uuid7()
    card = await create(c, board, todo, "a", client_id=me)
    body = {"id": card["id"], "fields": {"title": "b"}}
    seq = (await send(c, board, "card.update", body, client_id=me)).json()["seq"]
    back = {"id": card["id"], "fields": {"title": "a"}}
    r = await send(c, board, "card.update", back, client_id=me, undo=True, base_seq=seq)
    assert r.status_code == 200, r.text

    seq = (
        await send(c, board, "card.update", body, client_id=me, base_seq=r.json()["seq"])
    ).json()["seq"]
    await send(
        c,
        board,
        "card.update",
        {"id": card["id"], "fields": {"title": "c"}},
        client_id=other,
        base_seq=seq,
    )
    r = await send(c, board, "card.update", back, client_id=me, undo=True, base_seq=seq)
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "can't undo: changed by alice"


# --- children (M5: o / O in card mode) -----------------------------------------------------


async def child(c, board, parent, title="child", **kw):
    data = {"id": uuid7(), "parent_id": parent["id"], "title": title}
    for k in ("after_id", "before_id"):
        if k in kw:
            data[k] = kw.pop(k)
    return await send(c, board, "card.create", data, **kw)


async def test_child_create_next_to_siblings(setup):
    c, board, (todo, *_), _ = setup
    parent = await create(c, board, todo, "p")
    r = await child(c, board, parent, "one")
    assert r.status_code == 200, r.text
    one = r.json()["event"]["data"]["card"]
    assert one["parent_card_id"] == parent["id"] and one["status_id"] is None
    assert one["number"] == parent["number"] + 1
    three = (await child(c, board, parent, "three", after_id=one["id"])).json()["event"]["data"]
    two = (await child(c, board, parent, "two", before_id=three["card"]["id"])).json()["event"]
    zero = (await child(c, board, parent, "zero", before_id=one["id"])).json()["event"]
    assert two["data"]["card"] and zero["data"]["card"]
    kids = [x for x in (await loaded(c, board)).values() if x["parent_card_id"] == parent["id"]]
    titles = [x["title"] for x in sorted(kids, key=lambda x: x["position"].encode())]
    assert titles == ["zero", "one", "two", "three"]
    # The column still holds only the parent.
    assert await column_titles(c, board, todo) == ["p"]

    # Toggle and delete work on a child; restoring it needs a live parent.
    kid = one
    r = await send(c, board, "card.update", {"id": kid["id"], "fields": {"is_done": True}})
    assert r.status_code == 200, r.text
    seq = (await send(c, board, "card.delete", {"id": kid["id"]})).json()["seq"]
    r = await send(c, board, "card.restore", {"id": kid["id"]}, undo=True, base_seq=seq)
    assert r.status_code == 200, r.text


async def test_child_rules(setup):
    c, board, (todo, *_), _ = setup
    parent = await create(c, board, todo, "p")
    kid = (await child(c, board, parent)).json()["event"]["data"]["card"]

    r = await child(c, board, kid, "grandchild")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"

    r = await child(c, board, {"id": str(uuid7())})
    assert r.status_code == 404

    await send(c, board, "card.delete", {"id": parent["id"]})
    r = await child(c, board, parent, "late")
    assert r.status_code == 410
    assert r.json()["error"]["message"] == f"#{parent['number']} was deleted by alice"
