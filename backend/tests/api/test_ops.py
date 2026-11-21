"""POST /boards/{id}/ops through apply_op (plan §3.2–3.3), single client."""

import uuid

import pytest
from sqlalchemy import text

from tests.api.helpers import add_board, add_card, add_user
from tests.api.ops_helpers import PW, column_titles, create, login_as, op_body, send
from tests.conftest import PUBLIC_URL
from vwkanban.ids import uuid7


@pytest.fixture
async def setup(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    board, statuses = await add_board(engine, alice, "B")
    async with make_client() as c:
        await login_as(c, "alice")
        yield c, board, statuses, alice


async def board_row(engine, board):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT seq, next_number FROM boards WHERE id = :b"), {"b": board}
            )
        ).one()


async def event_count(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM board_events"))).scalar_one()


async def test_create_allocates_number_seq_and_logs_event(setup, engine):
    c, board, (todo, *_), _ = setup
    client_id = uuid7()
    body = op_body(
        "card.create",
        {"id": uuid7(), "status_id": todo, "title": "  First  ", "tags": ["ui", "bug"]},
        client_id=client_id,
    )
    r = await c.post(f"/api/boards/{board}/ops", json=body)
    assert r.status_code == 200, r.text
    ack = r.json()
    assert ack["t"] == "ack" and ack["seq"] == 1 and ack["op_id"] == body["op"]["op_id"]
    ev = ack["event"]
    assert ev["kind"] == "card.create" and ev["client_id"] == str(client_id)
    assert ev["actor"]["username"] == "alice"
    card = ev["data"]["card"]
    assert card["number"] == 1 and card["title"] == "First" and card["tags"] == ["ui", "bug"]
    assert card["position"] == "a0" and card["status_id"] == str(todo)
    meta = card["field_meta"]
    for f in ("title", "description", "tags", "date", "is_done", "position"):
        assert meta[f] == {"seq": 1, "client": str(client_id)}

    second = await create(c, board, todo, "Second")
    assert second["number"] == 2
    assert tuple(await board_row(engine, board)) == (2, 3)
    assert await event_count(engine) == 2
    loaded = (await c.get(f"/api/boards/{board}")).json()
    assert loaded["seq"] == 2
    assert [x["number"] for x in loaded["cards"]] == [1, 2]


async def test_placement_after_before_and_end(setup):
    c, board, (todo, doing, _), _ = setup
    a = await create(c, board, todo, "a")
    d = await create(c, board, todo, "d")  # no neighbour: end of column
    await create(c, board, todo, "b", after=a["id"])
    await create(c, board, todo, "c", before=d["id"])
    await create(c, board, todo, "0", before=a["id"])
    await create(c, board, todo, "e", after=d["id"])
    assert await column_titles(c, board, todo) == ["0", "a", "b", "c", "d", "e"]
    # A neighbour from another column is not in the target list → end of column.
    await create(c, board, doing, "x")
    await create(c, board, doing, "y", after=a["id"])
    assert await column_titles(c, board, doing) == ["x", "y"]


async def test_neighbour_fallback(setup):
    c, board, (todo, *_), _ = setup
    a = await create(c, board, todo, "a")
    b = await create(c, board, todo, "b")
    gone = await create(c, board, todo, "gone")
    assert (await send(c, board, "card.delete", {"id": gone["id"]})).status_code == 200
    # after_id deleted → before_id used
    await create(c, board, todo, "between", after=gone["id"], before=b["id"])
    # neither live → end of column
    await create(c, board, todo, "last", after=gone["id"], before=uuid7())
    assert await column_titles(c, board, todo) == ["a", "between", "b", "last"]
    assert a["position"] < b["position"]


async def test_toggle_done(setup):
    c, board, (todo, *_), _ = setup
    card = await create(c, board, todo)
    client_id = uuid7()
    r = await send(
        c,
        board,
        "card.update",
        {"id": card["id"], "fields": {"is_done": True}},
        client_id=client_id,
    )
    assert r.status_code == 200, r.text
    out = r.json()["event"]["data"]["card"]
    assert out["is_done"] is True
    assert out["field_meta"]["is_done"] == {"seq": 2, "client": str(client_id)}
    assert out["field_meta"]["title"]["seq"] == 1  # untouched fields keep their stamp
    loaded = (await c.get(f"/api/boards/{board}")).json()["cards"]
    assert loaded[0]["is_done"] is True


async def test_delete_cascades_to_children(setup, engine):
    c, board, (todo, *_), alice = setup
    parent = await create(c, board, todo, "parent")
    pid = uuid.UUID(parent["id"])
    child = await add_card(engine, board, alice, number=50, parent_id=pid)
    other = await create(c, board, todo, "other")
    assert len((await c.get(f"/api/boards/{board}")).json()["cards"]) == 3

    r = await send(c, board, "card.delete", {"id": parent["id"]})
    assert r.status_code == 200, r.text
    data = r.json()["event"]["data"]
    assert data["id"] == parent["id"]
    assert set(data["deleted_ids"]) == {parent["id"], str(child)}
    seq = r.json()["seq"]
    cards = (await c.get(f"/api/boards/{board}")).json()["cards"]
    assert [x["id"] for x in cards] == [other["id"]]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT field_meta FROM cards WHERE deleted_at IS NOT NULL ORDER BY number")
            )
        ).scalars()
        assert [m["deleted"]["seq"] for m in rows] == [seq, seq]


async def test_rejects(setup, engine):
    c, board, (todo, *_), alice = setup
    card = await create(c, board, todo)
    assert (await send(c, board, "card.delete", {"id": card["id"]})).status_code == 200
    seq_before = (await board_row(engine, board)).seq

    # deleted card → gone, with the op_id and a null current
    r = await send(c, board, "card.update", {"id": card["id"], "fields": {"is_done": True}})
    assert r.status_code == 410
    err = r.json()["error"]
    assert err["code"] == "gone" and err["current"] is None and "op_id" in err
    r = await send(c, board, "card.delete", {"id": card["id"]})
    assert r.status_code == 410

    # unknown card / a card of another board → not_found
    r = await send(c, board, "card.delete", {"id": uuid7()})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    other_board, (other_todo,) = await add_board(engine, alice, "Other", statuses=("Todo",))
    foreign = await create(c, other_board, other_todo)
    r = await send(c, board, "card.delete", {"id": foreign["id"]})
    assert r.status_code == 404

    # a column that isn't on this board → gone
    r = await send(c, board, "card.create", {"id": uuid7(), "status_id": other_todo, "title": "x"})
    assert r.status_code == 410

    # an id that already exists
    live = await create(c, board, todo)
    r = await send(c, board, "card.create", {"id": live["id"], "status_id": todo, "title": "x"})
    assert r.status_code == 422

    # rejects don't consume a seq; only the one successful create did
    assert (await board_row(engine, board)).seq == seq_before + 1


@pytest.mark.parametrize(
    "data",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 301},
        {"tags": ["a;b"]},
        {"tags": [""]},
        {"tags": ["x" * 31]},
        {"description": "x" * 20_001},
        {"date": "2026-13-01"},
        {"bogus": 1},
    ],
)
async def test_create_validation(setup, data):
    c, board, (todo, *_), _ = setup
    body = {"id": uuid7(), "status_id": todo, "title": "ok", **data}
    r = await send(c, board, "card.create", body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation"


@pytest.mark.parametrize(
    "op",
    [
        {"kind": "card.nope", "data": {}},
        {"kind": "card.update", "data": {"id": "x", "fields": {"is_done": True}}},
        {"kind": "card.update", "data": {"id": str(uuid7()), "fields": {"title": "t"}}},
        {"kind": "card.delete", "data": {"id": str(uuid7())}, "undo": True},
    ],
)
async def test_envelope_validation(setup, op):
    c, board, *_ = setup
    body = {"client_id": str(uuid7()), "op": {"op_id": str(uuid7()), "base_seq": 0, **op}}
    r = await c.post(f"/api/boards/{board}/ops", json=body)
    assert r.status_code == 422, r.text


async def test_idempotent_resend(setup, engine):
    c, board, (todo, *_), _ = setup
    body = op_body("card.create", {"id": uuid7(), "status_id": todo, "title": "once"})
    first = await c.post(f"/api/boards/{board}/ops", json=body)
    again = await c.post(f"/api/boards/{board}/ops", json=body)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert tuple(await board_row(engine, board)) == (1, 2)  # seq and numbers not advanced
    assert len((await c.get(f"/api/boards/{board}")).json()["cards"]) == 1
    assert await event_count(engine) == 1

    # A resent toggle replays its stored ack instead of applying again.
    card = first.json()["event"]["data"]["card"]
    toggle = op_body("card.update", {"id": card["id"], "fields": {"is_done": True}})
    r1 = await c.post(f"/api/boards/{board}/ops", json=toggle)
    await send(c, board, "card.update", {"id": card["id"], "fields": {"is_done": False}})
    r2 = await c.post(f"/api/boards/{board}/ops", json=toggle)
    assert r1.json() == r2.json()
    assert (await c.get(f"/api/boards/{board}")).json()["cards"][0]["is_done"] is False


async def test_op_id_from_another_board_is_rejected(setup, engine):
    c, board, (todo, *_), alice = setup
    other, (other_todo,) = await add_board(engine, alice, "Other", statuses=("Todo",))
    body = op_body("card.create", {"id": uuid7(), "status_id": todo, "title": "x"})
    assert (await c.post(f"/api/boards/{board}/ops", json=body)).status_code == 200
    body["op"]["data"] = {"id": str(uuid7()), "status_id": str(other_todo), "title": "x"}
    r = await c.post(f"/api/boards/{other}/ops", json=body)
    assert r.status_code == 422


async def test_ops_need_origin(setup, make_client, engine):
    _, board, (todo, *_), _ = setup
    async with make_client(origin="http://evil") as c:
        await login_as_with_origin(c)
        r = await send(c, board, "card.create", {"id": uuid7(), "status_id": todo, "title": "x"})
    assert r.status_code == 403
    assert await event_count(engine) == 0


async def login_as_with_origin(c) -> None:
    r = await c.post(
        "/api/auth/login",
        json={"username": "alice", "password": PW},
        headers={"Origin": PUBLIC_URL},
    )
    assert r.status_code == 200
