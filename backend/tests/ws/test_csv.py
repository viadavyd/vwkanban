"""CSV import over the board's sockets (plan §3.2 `board.import`, §3.6): the import is one
event in seq order, other clients learn of it (and resync), and it replays on reconnect."""

import asyncio

from tests.csv.helpers import HEADER, export, import_csv
from vwkanban.ids import uuid7

CSV = HEADER + "1,Imported,QA,,,,,\r\n2,Kid,,,1,true,,\r\n"


async def test_second_client_sees_board_import_and_resyncs(ab):
    ws, alice, bob, board, _, a, b = ab
    client = uuid7()
    r = await import_csv(alice.http, board, CSV, client_id=client)
    assert r.status_code == 200, r.text
    seq = r.json()["seq"]
    for sock in (a, b):  # the importer's own sockets get it too
        ev = await sock.expect("event", lambda m: m["kind"] == "board.import")
        assert ev["seq"] == seq
        assert ev["client_id"] == str(client)
        assert ev["actor"]["username"] == "alice"
        assert ev["data"] == {"created": 2, "statuses_created": ["QA"]}
    # Bob's resync (a fresh GET) has the imported cards and column at the event's seq.
    state = await ws.board_state(bob, board)
    assert state["seq"] == seq
    assert {c["title"] for c in state["cards"]} == {"Imported", "Kid"}
    assert "QA" in {s["name"] for s in state["statuses"]}
    # Round-trip: what bob exports imports back identically.
    first = await export(bob.http, board)
    r = await bob.http.post("/api/boards", json={"title": "copy"})
    copy = r.json()["id"]
    assert (await import_csv(bob.http, copy, first)).status_code == 200
    assert await export(bob.http, copy) == first


async def test_a_dry_run_sends_nothing(ab):
    ws, alice, bob, board, _, a, b = ab
    r = await import_csv(alice.http, board, CSV, dry_run=True)
    assert r.status_code == 200, r.text
    await b.send({"t": "ping"})
    await b.expect("pong")
    assert b.events() == []


async def test_import_and_ops_are_serialized_in_seq_order(ab):
    ws, alice, bob, board, (todo, *_), a, b = ab
    big = HEADER + "".join(f"{i},card {i},,,,,,\r\n" for i in range(1, 2001))
    imp = asyncio.create_task(import_csv(alice.http, board, big))
    op_ids = [
        await b.op("card.create", {"id": uuid7(), "status_id": todo, "title": f"op {i}"})
        for i in range(5)
    ]
    r = await imp
    assert r.status_code == 200, r.text
    for op_id in op_ids:
        await a.event_for(op_id)
    await a.expect("event", lambda m: m["kind"] == "board.import")
    seqs = [e["seq"] for e in a.events()]
    assert seqs == list(range(1, 7))  # one seq each, no gaps, in order
    state = await ws.board_state(alice, board)
    assert state["seq"] == 6
    assert len(state["cards"]) == 2005
    numbers = sorted(c["number"] for c in state["cards"])
    assert numbers == list(range(1, 2006))  # numbers never collide


async def test_reconnect_replays_board_import(ab):
    ws, alice, bob, board, (todo, *_), a, b = ab
    await a.event_for(await a.op("card.create", {"id": uuid7(), "status_id": todo, "title": "x"}))
    await b.close()
    r = await import_csv(alice.http, board, CSV)
    assert r.status_code == 200, r.text
    again = await ws.connect(bob, board, last_seq=1)
    ev = await again.expect("event", lambda m: m["kind"] == "board.import")
    assert ev["seq"] == r.json()["seq"] == 2
