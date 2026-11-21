"""§7: GET /boards/{id} < 150 ms server time on a 500-card board. Report-only unless
VWK_PERF_ENFORCE=1 (shared CI runners are noisy; enforced on the reference machine)."""

import os
import statistics
import time

from sqlalchemy import text

from tests.api.helpers import add_board, add_user, nth_key
from tests.api.ops_helpers import PW, login_as
from vwkanban.ids import uuid7

LIMIT_MS = 150


async def test_board_load_500_cards(engine, make_client):
    alice = await add_user(engine, "alice", PW)
    board, statuses = await add_board(engine, alice, "Perf")
    rows = [
        {
            "id": uuid7(),
            "b": board,
            "n": n,
            "s": statuses[n % 3],
            "pos": nth_key(n // 3),
            "t": f"card {n} with a realistic title",
            "tags": ["ui", f"t{n % 7}"],
            "u": alice,
        }
        for n in range(1, 501)
    ]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cards (id, board_id, number, status_id, position, title, tags,"
                " description, created_by) VALUES (:id, :b, :n, :s, :pos, :t, :tags,"
                " 'a description line', :u)"
            ),
            rows,
        )
    async with make_client() as c:
        await login_as(c, "alice")
        times = []
        for _ in range(11):
            t0 = time.perf_counter()
            r = await c.get(f"/api/boards/{board}")
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
        assert len(r.json()["cards"]) == 500
    median = statistics.median(times[1:])  # first call warms the pool
    print(f"\nperf: GET /boards/{{id}} with 500 cards: median {median:.1f} ms (limit {LIMIT_MS})")
    if os.environ.get("VWK_PERF_ENFORCE") == "1":
        assert median < LIMIT_MS
