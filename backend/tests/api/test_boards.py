import pytest
from sqlalchemy import text

from tests.api.helpers import add_board, add_card, add_member, add_user
from tests.conftest import PUBLIC_URL
from vwkanban.ids import uuid7

PW = "s3cret-pass"


async def login_as(c, username: str) -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200


@pytest.fixture
async def alice(engine):
    return await add_user(engine, "alice", PW)


@pytest.fixture
async def as_alice(make_client, alice):
    async with make_client() as c:
        await login_as(c, "alice")
        yield c


# --- access matrix -----------------------------------------------------------------


# Every /boards/{board_id}* route, with who may call it. The guard test below fails if a
# route is added without a row here.
def _create_op(status_ids):
    return {
        "client_id": str(uuid7()),
        "op": {
            "op_id": str(uuid7()),
            "kind": "card.create",
            "base_seq": 0,
            "data": {"id": str(uuid7()), "status_id": str(status_ids[0]), "title": "x"},
        },
    }


BOARD_ROUTES = [
    # method, path, json body (or a function of the board's status ids), minimum role
    ("GET", "/api/boards/{board_id}", None, "editor"),
    ("PATCH", "/api/boards/{board_id}", {"title": "Renamed"}, "owner"),
    ("DELETE", "/api/boards/{board_id}", None, "owner"),
    ("POST", "/api/boards/{board_id}/ops", _create_op, "editor"),
]


def test_access_matrix_covers_every_board_route(client):
    # The OpenAPI schema lists every route, however routers are nested.
    routes = {
        (method.upper(), path)
        for path, ops in client.app.openapi()["paths"].items()
        if "{board_id}" in path
        for method in ops
    }
    covered = {(method, path) for method, path, _, _ in BOARD_ROUTES}
    assert routes == covered


@pytest.mark.parametrize(("method", "path", "body", "min_role"), BOARD_ROUTES)
@pytest.mark.parametrize("who", ["stranger", "editor", "owner", "anonymous"])
async def test_access_matrix(make_client, engine, alice, method, path, body, min_role, who):
    board, status_ids = await add_board(engine, alice, "A's board")
    if callable(body):
        body = body(status_ids)
    bob = await add_user(engine, "bob", PW)
    if who == "editor":
        await add_member(engine, board, bob, "editor")

    async with make_client() as c:
        if who == "owner":
            await login_as(c, "alice")
        elif who in ("editor", "stranger"):
            await login_as(c, "bob")
        r = await c.request(method, path.format(board_id=board), json=body)

    expected = {
        "anonymous": 401,
        "stranger": 404,  # don't reveal that the board exists
        "editor": 403 if min_role == "owner" else None,
        "owner": None,
    }[who]
    if expected is None:
        assert r.status_code < 300, r.text
    else:
        assert r.status_code == expected, r.text
        assert "error" in r.json()

    async with engine.connect() as conn:
        title = (
            await conn.execute(text("SELECT title FROM boards WHERE id = :b"), {"b": board})
        ).scalar()
        cards = (await conn.execute(text("SELECT count(*) FROM cards"))).scalar_one()
    if expected is not None:
        assert title == "A's board"  # nothing changed
        assert cards == 0


async def test_stranger_does_not_see_board_in_list(make_client, engine, alice):
    await add_board(engine, alice, "A's board")
    await add_user(engine, "bob", PW)
    async with make_client() as c:
        await login_as(c, "bob")
        assert (await c.get("/api/boards")).json() == []


async def test_unknown_board_is_404(as_alice):
    r = await as_alice.get("/api/boards/0190a000-0000-7000-8000-000000000000")
    assert r.status_code == 404


async def test_board_list_needs_login(client):
    assert (await client.get("/api/boards")).status_code == 401
    assert (await client.post("/api/boards", json={"title": "x"})).status_code == 401


# --- summary -----------------------------------------------------------------------


async def test_summary_counts(make_client, engine, alice):
    b1, (todo, doing, done) = await add_board(engine, alice, "One")
    b2, _ = await add_board(engine, alice, "Two")
    bob = await add_user(engine, "bob", PW)
    hidden, hidden_st = await add_board(engine, bob, "Bob's")
    await add_card(engine, hidden, bob, number=1, status_id=hidden_st[0])

    n = iter(range(1, 100))
    await add_card(engine, b1, alice, number=next(n), status_id=todo)
    await add_card(engine, b1, alice, number=next(n), status_id=todo)
    parent = await add_card(engine, b1, alice, number=next(n), status_id=doing)
    await add_card(engine, b1, alice, number=next(n), parent_id=parent)  # child: not counted
    await add_card(engine, b1, alice, number=next(n), parent_id=parent, is_done=True)
    await add_card(engine, b1, alice, number=next(n), status_id=done, is_done=True)
    await add_card(engine, b1, alice, number=next(n), status_id=doing, is_done=True)
    await add_card(engine, b1, alice, number=next(n), status_id=done, deleted=True)  # deleted

    async with make_client() as c:
        await login_as(c, "alice")
        r = await c.get("/api/boards")
    assert r.status_code == 200
    items = r.json()
    assert [i["title"] for i in items] == ["One", "Two"]  # created order; Bob's is absent
    assert items[0]["role"] == "owner"
    assert items[0]["summary"] == {
        "total": 5,
        "done": 2,
        "by_status": [
            {"name": "Todo", "color": "gray", "count": 2},
            {"name": "Doing", "color": "gray", "count": 2},
            {"name": "Done", "color": "gray", "count": 1},
        ],
    }
    assert items[1]["summary"]["total"] == 0
    assert [s["count"] for s in items[1]["summary"]["by_status"]] == [0, 0, 0]


async def test_summary_follows_status_position(as_alice, engine, alice):
    b, (s1, s2, s3) = await add_board(engine, alice, "B", statuses=("X", "Y", "Z"))
    # Byte order (collation "C"): 'Zz' < 'a2' < 'a3'. A locale collation would give a2, a3, Zz.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE statuses SET position = 'a3' WHERE id = :s"), {"s": s1})
        await conn.execute(text("UPDATE statuses SET position = 'Zz' WHERE id = :s"), {"s": s2})
    r = await as_alice.get("/api/boards")
    assert [s["name"] for s in r.json()[0]["summary"]["by_status"]] == ["Y", "Z", "X"]


async def test_board_without_columns(as_alice, engine, alice):
    await add_board(engine, alice, "Empty", statuses=())
    item = (await as_alice.get("/api/boards")).json()[0]
    assert item["summary"] == {"total": 0, "done": 0, "by_status": []}


# --- create / rename / delete / detail ---------------------------------------------


async def test_create_seeds_columns_and_owner(as_alice, alice):
    r = await as_alice.post("/api/boards", json={"title": "  Hackathon  "})
    assert r.status_code == 201
    item = r.json()
    assert item["title"] == "Hackathon"
    assert item["role"] == "owner"
    assert [(s["name"], s["color"]) for s in item["summary"]["by_status"]] == [
        ("Todo", "gray"),
        ("Doing", "blue"),
        ("Done", "green"),
    ]

    detail = (await as_alice.get(f"/api/boards/{item['id']}")).json()
    assert detail["seq"] == 0
    assert detail["cards"] == []
    assert [s["position"] for s in detail["statuses"]] == ["a0", "a1", "a2"]
    assert detail["members"] == [{"user_id": str(alice), "username": "alice", "role": "owner"}]
    assert detail["board"]["created_by"] == str(alice)


@pytest.mark.parametrize("title", ["", "   ", "x" * 121, None])
async def test_title_validation(as_alice, engine, alice, title):
    r = await as_alice.post("/api/boards", json={"title": title})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation"
    board, _ = await add_board(engine, alice, "Keep")
    r = await as_alice.patch(f"/api/boards/{board}", json={"title": title})
    assert r.status_code == 422


async def test_rename_bumps_updated_at(as_alice, engine, alice):
    board, _ = await add_board(engine, alice, "Old")
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE boards SET updated_at = now() - interval '1 day'"))
    before = (await as_alice.get("/api/boards")).json()[0]["updated_at"]
    r = await as_alice.patch(f"/api/boards/{board}", json={"title": "New"})
    assert r.status_code == 200
    assert r.json()["title"] == "New"
    assert r.json()["updated_at"] > before


async def test_delete_removes_board_and_rows(as_alice, engine, alice):
    board, statuses = await add_board(engine, alice, "Gone")
    await add_card(engine, board, alice, number=1, status_id=statuses[0])
    assert (await as_alice.delete(f"/api/boards/{board}")).status_code == 204
    assert (await as_alice.get(f"/api/boards/{board}")).status_code == 404
    assert (await as_alice.get("/api/boards")).json() == []
    async with engine.connect() as conn:
        for table in ("boards", "board_members", "statuses", "cards"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_board_writes_need_origin(make_client, engine, alice, method):
    board, _ = await add_board(engine, alice, "A")
    async with make_client() as c:
        await login_as(c, "alice")
        path = "/api/boards" if method == "POST" else f"/api/boards/{board}"
        r = await c.request(method, path, json={"title": "x"}, headers={"Origin": "http://evil"})
    assert r.status_code == 403
    async with make_client(origin=PUBLIC_URL) as c:
        await login_as(c, "alice")
        assert len((await c.get("/api/boards")).json()) == 1


async def test_board_load_returns_live_cards(as_alice, engine, alice):
    board, (todo, doing, _) = await add_board(engine, alice, "B")
    other, (other_todo, *_) = await add_board(engine, alice, "Other")
    c2 = await add_card(engine, board, alice, number=2, status_id=todo)
    c1 = await add_card(engine, board, alice, number=1, status_id=todo)
    c3 = await add_card(engine, board, alice, number=3, status_id=doing, is_done=True)
    child = await add_card(engine, board, alice, number=4, parent_id=c3)
    await add_card(engine, board, alice, number=5, status_id=todo, deleted=True)
    await add_card(engine, other, alice, number=1, status_id=other_todo)

    cards = (await as_alice.get(f"/api/boards/{board}")).json()["cards"]
    by_id = {c["id"]: c for c in cards}
    assert set(by_id) == {str(c1), str(c2), str(c3), str(child)}
    todo_ids = [c["id"] for c in cards if c["status_id"] == str(todo)]
    assert todo_ids == [str(c1), str(c2)]  # by position (nth_key(number))
    assert by_id[str(child)]["parent_card_id"] == str(c3)
    assert by_id[str(child)]["status_id"] is None
    assert by_id[str(c3)]["is_done"] is True
    assert set(by_id[str(c1)]) >= {"number", "position", "title", "tags", "date", "field_meta"}
