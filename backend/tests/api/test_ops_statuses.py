"""Column ops (status.*) through apply_op, the status delete rule (plan §2) and column
undo, single client."""

import uuid

import pytest
from sqlalchemy import text

from tests.api.helpers import add_board, add_card, add_user
from tests.api.ops_helpers import PW, create, login_as, send
from vwkanban.ids import uuid7


@pytest.fixture
async def setup(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    board, statuses = await add_board(engine, alice, "B")
    async with make_client() as c:
        await login_as(c, "alice")
        yield c, board, statuses, alice


async def names(c, board) -> list[str]:
    st = (await c.get(f"/api/boards/{board}")).json()["statuses"]
    return [s["name"] for s in sorted(st, key=lambda s: s["position"].encode())]


async def add_status(c, board, name, *, after=None, before=None, color="blue", **kw):
    data = {"id": uuid7(), "name": name, "color": color}
    if after:
        data["after_id"] = after
    if before:
        data["before_id"] = before
    return await send(c, board, "status.create", data, **kw)


async def test_create_placement(setup):
    c, board, (todo, doing, done), _ = setup
    r = await add_status(c, board, "  Review ", after=doing)
    assert r.status_code == 200, r.text
    st = r.json()["event"]["data"]["status"]
    assert st["name"] == "Review" and st["color"] == "blue"
    assert set(st["field_meta"]) == {"name", "color", "position", "created"}
    await add_status(c, board, "First", before=todo)
    await add_status(c, board, "Last")  # no neighbour → end
    await add_status(c, board, "Gone-neighbour", after=uuid7())  # unknown → end
    assert await names(c, board) == [
        "First",
        "Todo",
        "Doing",
        "Review",
        "Done",
        "Last",
        "Gone-neighbour",
    ]
    assert done


@pytest.mark.parametrize(
    "data",
    [
        {"name": ""},
        {"name": "x" * 41},
        {"color": "teal"},
        {"bogus": 1},
    ],
)
async def test_create_validation(setup, data):
    c, board, *_ = setup
    body = {"id": uuid7(), "name": "ok", "color": "red", **data}
    assert (await send(c, board, "status.create", body)).status_code == 422


async def test_duplicate_names_and_ids(setup):
    c, board, (todo, doing, _), _ = setup
    r = await add_status(c, board, "todo")  # case-insensitive
    assert r.status_code == 422 and "already exists" in r.json()["error"]["message"]
    r = await send(c, board, "status.create", {"id": todo, "name": "Fresh", "color": "red"})
    assert r.status_code == 422
    r = await send(c, board, "status.update", {"id": doing, "name": "TODO"})
    assert r.status_code == 422
    # Renaming to its own name (other case) is fine.
    r = await send(c, board, "status.update", {"id": doing, "name": "DOING"})
    assert r.status_code == 200


async def test_update_rename_and_color(setup):
    c, board, (todo, *_), _ = setup
    r = await send(c, board, "status.update", {"id": todo, "color": "green"})
    assert r.status_code == 200
    st = r.json()["event"]["data"]["status"]
    assert st["color"] == "green" and st["name"] == "Todo"
    assert set(st["field_meta"]) == {"color"}  # seeded columns had no stamps
    r = await send(c, board, "status.update", {"id": todo, "name": "Backlog"})
    assert r.json()["event"]["data"]["status"]["name"] == "Backlog"
    assert (await send(c, board, "status.update", {"id": todo})).status_code == 422
    r = await send(c, board, "status.update", {"id": uuid7(), "name": "x"})
    assert r.status_code == 410


async def test_move(setup):
    c, board, (todo, doing, done), _ = setup
    r = await send(c, board, "status.move", {"id": todo, "after_id": doing})
    assert r.status_code == 200
    assert await names(c, board) == ["Doing", "Todo", "Done"]
    await send(c, board, "status.move", {"id": done, "before_id": doing})
    assert await names(c, board) == ["Done", "Doing", "Todo"]
    await send(c, board, "status.move", {"id": done})  # no neighbour → end
    assert await names(c, board) == ["Doing", "Todo", "Done"]


async def test_delete_rejected_while_column_has_live_cards(setup, engine):
    c, board, (todo, *_), _ = setup
    await create(c, board, todo)
    async with engine.connect() as conn:
        seq = (await conn.execute(text("SELECT seq FROM boards"))).scalar_one()
    r = await send(c, board, "status.delete", {"id": todo})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation" and "not empty" in err["message"]
    assert err["current"]["id"] == str(todo)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT seq FROM boards"))).scalar_one() == seq
    assert "Todo" in await names(c, board)


async def test_delete_purges_soft_deleted_cards_and_their_undo_is_gone(setup, engine):
    c, board, (todo, doing, _), alice = setup
    me = uuid7()
    r = await send(
        c, board, "card.create", {"id": uuid7(), "status_id": doing, "title": "x"}, client_id=me
    )
    card = r.json()["event"]["data"]["card"]
    child = await add_card(engine, board, alice, number=50, parent_id=uuid.UUID(card["id"]))
    del_seq = (await send(c, board, "card.delete", {"id": card["id"]}, client_id=me)).json()["seq"]
    keep = await create(c, board, todo, "elsewhere")

    r = await send(c, board, "status.delete", {"id": doing}, client_id=me)
    assert r.status_code == 200, r.text
    assert r.json()["event"]["data"] == {"id": str(doing), "purged_ids": [card["id"]]}
    async with engine.connect() as conn:
        ids = (await conn.execute(text("SELECT id FROM cards"))).scalars().all()
    assert [str(i) for i in ids] == [keep["id"]]  # the card and its child are gone
    assert str(child) not in ids

    r = await send(
        c, board, "card.restore", {"id": card["id"]}, client_id=me, undo=True, base_seq=del_seq
    )
    assert r.status_code == 410 and r.json()["error"]["code"] == "gone"


async def test_undo_of_delete_recreates_leftmost_column_with_same_id(setup):
    c, board, (todo, doing, _), _ = setup
    me = uuid7()
    seq = (await send(c, board, "status.delete", {"id": todo}, client_id=me)).json()["seq"]
    r = await send(
        c,
        board,
        "status.create",
        {"id": todo, "name": "Todo", "color": "gray", "before_id": doing},
        client_id=me,
        undo=True,
        base_seq=seq,
    )
    assert r.status_code == 200, r.text
    assert await names(c, board) == ["Todo", "Doing", "Done"]
    # Cards can go into it again.
    await create(c, board, todo)


async def test_column_undo_checks_field_meta(setup):
    c, board, (todo, doing, _), _ = setup
    me, other = uuid7(), uuid7()
    seq = (await send(c, board, "status.update", {"id": todo, "name": "A"}, client_id=me)).json()[
        "seq"
    ]
    # Another client recolours: undoing my rename is fine (different field).
    await send(c, board, "status.update", {"id": todo, "color": "red"}, client_id=other)
    r = await send(
        c,
        board,
        "status.update",
        {"id": todo, "name": "Todo"},
        client_id=me,
        undo=True,
        base_seq=seq,
    )
    assert r.status_code == 200

    seq = (
        await send(c, board, "status.move", {"id": todo, "after_id": doing}, client_id=me)
    ).json()["seq"]
    await send(c, board, "status.move", {"id": todo}, client_id=other)
    r = await send(
        c,
        board,
        "status.move",
        {"id": todo, "before_id": doing},
        client_id=me,
        undo=True,
        base_seq=seq,
    )
    assert r.status_code == 409 and r.json()["error"]["message"] == "can't undo: changed by alice"

    # Undo of a create (= delete) conflicts once someone else renamed the new column.
    r = await add_status(c, board, "New", client_id=me)
    new, seq = r.json()["event"]["data"]["status"], r.json()["seq"]
    await send(c, board, "status.update", {"id": new["id"], "name": "Theirs"}, client_id=other)
    r = await send(
        c, board, "status.delete", {"id": new["id"]}, client_id=me, undo=True, base_seq=seq
    )
    assert r.status_code == 409
