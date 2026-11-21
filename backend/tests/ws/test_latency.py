"""Remote-change latency (plan §7): A sends 200 ops paced at 40 ops/s, B timestamps the
events. Targets: remote p95 < 300 ms; server apply p95 < 30 ms.

Apply time is measured first, one op in flight (no queueing): A's ack round-trip minus
the median ping round-trip (a ping is the same path with no apply). In CI, a 20 ms
netem delay is put on the test server's port only (VWK_WS_PORT), so DB round-trips
aren't delayed.

Report-only unless VWK_PERF_ENFORCE=1 (shared CI runners are noisy)."""

import asyncio
import os
import statistics
import time

from tests.ws.test_ws import new_card

OPS = 200
RATE = 40
REMOTE_P95_MS = 300
APPLY_P95_MS = 30


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20)[-1]


async def test_remote_latency(ws):
    alice = await ws.user("alice")
    bob = await ws.user("bob")
    board, (todo, doing, _) = await ws.board(alice, bob)
    a = await ws.connect(alice, board)
    b = await ws.connect(bob, board)

    pings = []
    for _ in range(20):
        t0 = time.perf_counter()
        await a.send({"t": "ping"})
        await a.expect("pong")
        pings.append(time.perf_counter() - t0)
    ping_ms = statistics.median(pings) * 1000

    apply = []
    for i in range(50):
        t0 = time.perf_counter()
        op_id = await a.op("card.create", new_card(todo, f"warm{i}"))
        await a.answer(op_id)
        apply.append(max(0.0, (time.perf_counter() - t0) * 1000 - ping_ms))

    sent_at: dict[str, float] = {}
    card = None
    for i in range(OPS):
        if card is None or i % 2 == 0:
            data, kind = new_card(todo, f"c{i}"), "card.create"
        else:
            data, kind = {"id": card, "status_id": doing}, "card.move"
        t0 = time.perf_counter()
        op_id = await a.op(kind, data)
        sent_at[op_id] = t0
        if kind == "card.create":
            card = str(data["id"])
        await asyncio.sleep(1 / RATE)

    remote = []
    for op_id, t0 in sent_at.items():
        ack = await a.answer(op_id)
        assert ack["t"] == "ack", ack
        ev = await b.event_for(op_id)
        i = next(j for j, m in enumerate(b.messages) if m is ev)
        remote.append((b.arrival_times[i] - t0) * 1000)

    remote_p95, apply_p95 = p95(remote), p95(apply)
    print(
        f"\nperf: remote change p95 {remote_p95:.1f} ms at {RATE} ops/s (limit "
        f"{REMOTE_P95_MS}); apply p95 {apply_p95:.1f} ms (limit {APPLY_P95_MS}); "
        f"ping {ping_ms:.1f} ms; "
        f"netem port {os.environ.get('VWK_WS_PORT', 'none')}"
    )
    if os.environ.get("VWK_PERF_ENFORCE") == "1":
        assert remote_p95 < REMOTE_P95_MS
        assert apply_p95 < APPLY_P95_MS
