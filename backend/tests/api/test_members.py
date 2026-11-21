"""Members API (plan §3.1): list for members, add/remove for the owner."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api.helpers import add_board, add_member, add_user
from tests.api.ops_helpers import PW, login_as
from vwkanban.auth.models import User
from vwkanban.boards.deps import load_membership
from vwkanban.errors import ApiError
from vwkanban.ids import uuid7
from vwkanban.sync.ops import apply_op
from vwkanban.sync.schemas import CardCreate


@pytest.fixture
async def setup(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    bob = await add_user(engine, "bob", PW)
    board, _ = await add_board(engine, alice, "Shared")
    async with make_client() as a, make_client() as b:
        await login_as(a, "alice")
        await login_as(b, "bob")
        yield a, b, board, alice, bob


async def test_add_list_remove(setup):
    a, b, board, alice, bob = setup
    assert (await b.get(f"/api/boards/{board}")).status_code == 404
    r = await a.post(f"/api/boards/{board}/members", json={"username": " Bob "})
    assert r.status_code == 201, r.text
    assert r.json() == {"user_id": str(bob), "username": "bob", "role": "editor"}

    listed = (await b.get(f"/api/boards/{board}/members")).json()
    assert listed == [
        {"user_id": str(alice), "username": "alice", "role": "owner"},
        {"user_id": str(bob), "username": "bob", "role": "editor"},
    ]
    assert (await b.get(f"/api/boards/{board}")).status_code == 200
    # bob's dashboard shows the board as an editor's.
    assert [x["role"] for x in (await b.get("/api/boards")).json()] == ["editor"]

    assert (await a.delete(f"/api/boards/{board}/members/{bob}")).status_code == 204
    assert (await b.get(f"/api/boards/{board}")).status_code == 404


async def test_unknown_user_is_404(setup):
    a, _, board, *_ = setup
    r = await a.post(f"/api/boards/{board}/members", json={"username": "nobody"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_adding_twice_is_conflict(setup):
    a, _, board, *_ = setup
    assert (
        await a.post(f"/api/boards/{board}/members", json={"username": "bob"})
    ).status_code == 201
    r = await a.post(f"/api/boards/{board}/members", json={"username": "bob"})
    assert r.status_code == 409


async def test_owner_cant_be_removed(setup):
    a, _, board, alice, _ = setup
    r = await a.delete(f"/api/boards/{board}/members/{alice}")
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "the board owner can't be removed"


async def test_removing_a_non_member_is_404(setup):
    a, _, board, _, bob = setup
    assert (await a.delete(f"/api/boards/{board}/members/{bob}")).status_code == 404


async def test_editor_can_list_but_not_change(setup, engine):
    a, b, board, alice, bob = setup
    await add_member(engine, board, bob, "editor")
    await add_user(engine, "carol", PW)
    assert (await b.get(f"/api/boards/{board}/members")).status_code == 200
    r = await b.post(f"/api/boards/{board}/members", json={"username": "carol"})
    assert r.status_code == 403
    assert (await b.delete(f"/api/boards/{board}/members/{bob}")).status_code == 403


async def test_op_racing_removal_is_forbidden(setup, engine):
    """apply_op re-checks membership under the board lock: an op whose access check ran
    before the member was removed is refused, and writes nothing."""
    a, _, board, _, bob = setup
    await add_member(engine, board, bob, "editor")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = await db.get_one(User, bob)
        member = await load_membership(db, board, user)
        assert member is not None
        assert (await a.delete(f"/api/boards/{board}/members/{bob}")).status_code == 204
        statuses = (await a.get(f"/api/boards/{board}")).json()["statuses"]
        op = CardCreate(
            op_id=uuid7(),
            kind="card.create",
            base_seq=0,
            data={"id": uuid7(), "status_id": statuses[0]["id"], "title": "late"},
        )
        with pytest.raises(ApiError) as e:
            await apply_op(db, member, uuid7(), op)
    assert e.value.status_code == 403 and e.value.code == "forbidden"
    assert (await a.get(f"/api/boards/{board}")).json()["cards"] == []
