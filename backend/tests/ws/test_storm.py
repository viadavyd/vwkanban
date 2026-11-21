"""Random concurrent op storm (plan §6, M4 accept): 3 clients, each paced below the
50 ops/s limit, converge with each other and with a fresh GET."""

import asyncio
import random

from tests.ws.test_walkthroughs import converged
from tests.ws.test_ws import new_card

CLIENTS = 3
OPS_EACH = 120
RATE = 40  # ops/s per client


async def _storm(c, statuses, rng: random.Random) -> list[str]:
    """Random creates, moves, toggles and deletes over the cards this client has seen.
    Ops on cards a teammate just deleted are rejected (`gone`); that's part of it."""
    sent = []
    for _ in range(OPS_EACH):
        live = {}
        for e in c.events():
            d = e["data"]
            if card := d.get("card"):
                live[card["id"]] = card
            for i in d.get("deleted_ids", []):
                live.pop(i, None)
        roll = rng.random()
        if not live or roll < 0.4:
            after = rng.choice([None, *live]) if live else None
            data = new_card(rng.choice(statuses), "s", **({"after_id": after} if after else {}))
            sent.append(await c.op("card.create", data))
        elif roll < 0.7:
            cid = rng.choice(list(live))
            sent.append(await c.op("card.move", {"id": cid, "status_id": rng.choice(statuses)}))
        elif roll < 0.9:
            cid = rng.choice(list(live))
            fields = {"is_done": not live[cid]["is_done"]}
            sent.append(await c.op("card.update", {"id": cid, "fields": fields}))
        else:
            sent.append(await c.op("card.delete", {"id": rng.choice(list(live))}))
        await asyncio.sleep(1 / RATE)
    return sent


async def test_three_clients_converge(ws):
    users = [await ws.user(n) for n in ("alice", "bob", "carol")]
    board, statuses = await ws.board(users[0], *users[1:])
    clients = [await ws.connect(u, board) for u in users]
    sent = await asyncio.gather(
        *(_storm(c, statuses, random.Random(i)) for i, c in enumerate(clients))
    )
    answers = [
        [await c.answer(op_id) for op_id in ids] for c, ids in zip(clients, sent, strict=True)
    ]
    acked = sum(a["t"] == "ack" for row in answers for a in row)
    rejected = [a for row in answers for a in row if a["t"] == "reject"]
    assert {r["code"] for r in rejected} <= {"gone"}
    state = await converged(ws, users[0], board, *clients)
    assert state["seq"] == acked
    print(f"\nstorm: {acked} acked, {len(rejected)} gone, {len(state['cards'])} live cards")
