"""Plan §3.5 rows that need card mode (M5): text fields with a frozen base_seq, children.
Two real sockets, A (alice) and B (bob), on one board; every test ends with a fresh GET
that agrees with what the sockets saw."""

from sqlalchemy.ext.asyncio import AsyncSession

from tests.ws.test_walkthroughs import converged, ok
from tests.ws.test_ws import new_card
from vwkanban.ids import uuid7
from vwkanban.sync.models import trim_events


def fields(card, **f) -> dict:
    return {"id": card["id"], "fields": f}


async def rejected(c, kind, data, **kw) -> dict:
    op_id = await c.op(kind, data, **kw)
    ans = await c.answer(op_id)
    assert ans["t"] == "reject", ans
    return ans


def card_in(state, card) -> dict:
    return next(c for c in state["cards"] if c["id"] == card["id"])


async def test_description_vs_title_both_apply(ab):
    """Row 3: different fields → both applied, whatever the bases."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    base = 1
    ea = await ok(a, "card.update", fields(card, description="from A"), base_seq=base)
    eb = await ok(b, "card.update", fields(card, title="from B"), base_seq=base)
    assert eb["data"]["card"]["description"] == "from A"
    assert (await a.event_for(eb["op_id"]))["data"]["card"]["title"] == "from B"
    assert (await b.event_for(ea["op_id"]))["seq"] == ea["seq"]
    state = await converged(ws, alice, board, a, b)
    got = card_in(state, card)
    assert (got["title"], got["description"]) == ("from B", "from A")


async def test_due_time_reaches_the_other_client(ab):
    """A due date with a time is one text field: B sees it, and a stale write conflicts."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "due")))["data"]["card"]
    base = 1
    ea = await ok(a, "card.update", fields(card, date="2026-11-30 14:30"), base_seq=base)
    assert (await b.event_for(ea["op_id"]))["data"]["card"]["date"] == "2026-11-30 14:30"
    rej = await rejected(b, "card.update", fields(card, date="2026-12-01 09:00"), base_seq=base)
    assert rej["code"] == "conflict" and rej["current"]["date"] == "2026-11-30 14:30"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["date"] == "2026-11-30 14:30"


async def test_both_edit_the_description(ab):
    """Row 4: first save wins; the second gets `conflict` with the current card (the
    client keeps its draft), and `:w!` (base = current seq) then wins."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    base = 1  # both opened the field at seq 1
    first = await ok(a, "card.update", fields(card, description="A's text"), base_seq=base)
    rej = await rejected(b, "card.update", fields(card, description="B's text"), base_seq=base)
    assert rej["code"] == "conflict"
    assert rej["message"] == f"#{card['number']}'s description was changed by alice"
    assert rej["current"]["description"] == "A's text"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["description"] == "A's text"
    assert state["seq"] == first["seq"]  # the reject consumed no seq

    forced = await ok(b, "card.update", fields(card, description="B's text"), base_seq=state["seq"])
    assert (await a.event_for(forced["op_id"]))["data"]["card"]["description"] == "B's text"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["description"] == "B's text"


async def test_base_seq_frozen_at_field_entry(ab):
    """Row 5: B enters the field at seq S; A saves at S+1 and B applies that event; B's
    save still carries base S (frozen) → `conflict`, not a silent overwrite."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    for i in range(3):  # unrelated traffic moves the seq on
        await ok(a, "card.create", new_card(todo, f"x{i}"))
    entered = 4
    saved = await ok(a, "card.update", fields(card, description="A"), base_seq=4)
    assert (await b.event_for(saved["op_id"]))["seq"] == entered + 1
    rej = await rejected(b, "card.update", fields(card, description="B"), base_seq=entered)
    assert rej["code"] == "conflict" and rej["current"]["description"] == "A"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["description"] == "A"


async def test_conflict_after_the_log_was_trimmed(ab):
    """Row 6: the check reads cards.field_meta, not the event log, so it holds after the
    log is trimmed (the message then can't name who)."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    await ok(a, "card.update", fields(card, description="A"), base_seq=1)
    async with AsyncSession(ws.engine) as db:
        await trim_events(db, keep=0)
    rej = await rejected(b, "card.update", fields(card, description="B"), base_seq=1)
    assert rej["code"] == "conflict"
    assert rej["message"] == f"#{card['number']}'s description was changed by another user"
    state = await ws.board_state(alice, board)
    assert card_in(state, card)["description"] == "A"


async def test_saving_twice_is_no_self_conflict(ab):
    """Row 7: `:w`, `:w` from one tab, both with the base frozen at entry → both apply."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(b, "card.create", new_card(todo, "5")))["data"]["card"]
    await ok(a, "card.update", fields(card, title="one"), base_seq=1)
    second = await ok(a, "card.update", fields(card, title="two"), base_seq=1)
    assert (await b.event_for(second["op_id"]))["data"]["card"]["title"] == "two"
    # Another tab of the same user is another client: it does conflict.
    a2 = await ws.connect(alice, board)
    rej = await rejected(a2, "card.update", fields(card, title="three"), base_seq=1)
    assert rej["code"] == "conflict"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["title"] == "two"


async def test_edit_after_a_remote_delete_is_gone(ab):
    """Row 10 (server side): A was editing #5 when B deleted it; A's save gets `gone`
    naming B (the client keeps the draft and puts it in the register)."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    deleted = await ok(b, "card.delete", {"id": card["id"]})
    assert (await a.event_for(deleted["op_id"]))["data"]["deleted_ids"] == [card["id"]]
    rej = await rejected(a, "card.update", fields(card, description="draft"), base_seq=1)
    assert rej["code"] == "gone"
    assert rej["message"] == f"#{card['number']} was deleted by bob"
    state = await converged(ws, alice, board, a, b)
    assert state["cards"] == []


async def test_child_under_a_deleted_parent(ab):
    """Row 11: A adds a child (`o`) to #5 just after B deleted #5 → `gone`."""
    ws, alice, _, board, (todo, *_), a, b = ab
    parent = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    await ok(b, "card.delete", {"id": parent["id"]})
    rej = await rejected(
        a, "card.create", {"id": uuid7(), "parent_id": parent["id"], "title": "typed"}
    )
    assert rej["code"] == "gone"
    assert rej["message"] == f"#{parent['number']} was deleted by bob"
    state = await converged(ws, alice, board, a, b)
    assert state["cards"] == []


async def test_no_grandchildren(ab):
    ws, alice, _, board, (todo, *_), a, b = ab
    parent = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    kid = await ok(b, "card.create", {"id": uuid7(), "parent_id": parent["id"], "title": "k"})
    rej = await rejected(
        a, "card.create", {"id": uuid7(), "parent_id": kid["data"]["card"]["id"], "title": "g"}
    )
    assert rej["code"] == "validation"
    await converged(ws, alice, board, a, b)


async def test_children_sync_to_the_other_client(ab):
    """`o`, `O`, Space and `d` on children reach B in order; the parent's position and
    column don't change."""
    ws, alice, _, board, (todo, *_), a, b = ab
    parent = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    one = await ok(a, "card.create", {"id": uuid7(), "parent_id": parent["id"], "title": "1"})
    one_id = one["data"]["card"]["id"]
    zero = await ok(
        a,
        "card.create",
        {"id": uuid7(), "parent_id": parent["id"], "title": "0", "before_id": one_id},
    )
    done = await ok(a, "card.update", {"id": one_id, "fields": {"is_done": True}})
    gone = await ok(a, "card.delete", {"id": zero["data"]["card"]["id"]})
    seen = {e["op_id"]: await b.event_for(e["op_id"]) for e in (one, zero, done, gone)}
    assert [s["seq"] for s in seen.values()] == [e["seq"] for e in (one, zero, done, gone)]
    toggled = seen[done["op_id"]]["data"]["card"]
    assert toggled["parent_card_id"] == parent["id"] and toggled["is_done"] is True
    state = await converged(ws, alice, board, a, b)
    kids = [c for c in state["cards"] if c["parent_card_id"] == parent["id"]]
    assert [(c["title"], c["is_done"]) for c in kids] == [("1", True)]
    assert card_in(state, parent)["position"] == parent["position"]


async def test_undo_of_a_text_edit_after_a_teammate_edit(ab):
    """Row 13 for text: A's `u` would revert B's newer title → `conflict`."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "old")))["data"]["card"]
    mine = await ok(a, "card.update", fields(card, title="mine"), base_seq=1)
    await ok(b, "card.update", fields(card, title="bob's"), base_seq=mine["seq"])
    rej = await rejected(
        a, "card.update", fields(card, title="old"), base_seq=mine["seq"], undo=True
    )
    assert rej["code"] == "conflict" and rej["message"] == "can't undo: changed by bob"
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["title"] == "bob's"


async def test_long_unicode_description_fits_a_message(ab):
    """20 000 four-byte characters (~80 KB of UTF-8) fit the 128 KB WS cap."""
    ws, alice, _, board, (todo, *_), a, b = ab
    card = (await ok(a, "card.create", new_card(todo, "5")))["data"]["card"]
    text = "😀" * 20_000
    e = await ok(a, "card.update", fields(card, description=text), base_seq=1)
    assert (await b.event_for(e["op_id"]))["data"]["card"]["description"] == text
    state = await converged(ws, alice, board, a, b)
    assert card_in(state, card)["description"] == text
