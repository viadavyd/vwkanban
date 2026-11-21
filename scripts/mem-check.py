"""Plan §7 memory: idle total < 300 MB; 20 clients on a 500-card board < 600 MB.

Measures a running compose stack (docker stats over the project's containers):
  1. idle: the stack as it is (run it right after `up`, before anything else);
  2. load: one login, a 500-card board from one CSV import, then 20 clients that each
     load the board and hold its WebSocket, while ops (done toggles, LWW) go out at
     20 ops/s for 30 s and fan out to every socket. The peak sample counts.

  cd backend && uv run python ../scripts/mem-check.py --url http://localhost:8089 \\
      --project vwk-perf --env ../path/to/.env

Report-only unless VWK_PERF_ENFORCE=1. Uses the backend's own dependencies only
(`websockets`, plus `vwkanban.ids.uuid7` for op ids)."""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from http.cookiejar import CookieJar

from websockets.asyncio.client import connect

from vwkanban.ids import uuid7

IDLE_LIMIT_MB = 300
LOAD_LIMIT_MB = 600
CLIENTS = 20
CARDS = 500
OPS_PER_SECOND = 20
SECONDS = 30

UNITS = {
    "B": 1 / 2**20,
    "KiB": 1 / 2**10,
    "MiB": 1,
    "GiB": 2**10,
    "kB": 1e3 / 2**20,
    "MB": 1e6 / 2**20,
    "GB": 1e9 / 2**20,
}


def stack_mb(project: str) -> float:
    """Total memory of the project's containers, in MiB (one `docker stats` sample)."""
    ids = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not ids:
        sys.exit(f"no running containers in compose project {project!r}")
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", *ids],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    total = 0.0
    for line in out.splitlines():
        m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", line)
        if not m:
            sys.exit(f"can't parse docker stats line: {line!r}")
        total += float(m[1]) * UNITS[m[2]]
    return total


def read_env(path: str) -> dict[str, str]:
    env = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


class Api:
    def __init__(self, url: str) -> None:
        self.url = url
        self.jar = CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, content_type="application/json"):
        if body is not None and content_type == "application/json":
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        req = urllib.request.Request(self.url + path, data=body, method=method)
        req.add_header("Origin", self.url)
        if body is not None:
            req.add_header("Content-Type", content_type)
        with self.http.open(req, timeout=60) as r:
            return json.loads(r.read() or b"null")

    @property
    def session(self) -> str:
        return next(c.value for c in self.jar if c.name == "vwk_session")


async def client(api: Api, board_id: str, ready, stop, sender, counts: dict[str, int]):
    await asyncio.to_thread(api.call, "GET", f"/api/boards/{board_id}")  # as a browser does
    ws_url = api.url.replace("http", "ws", 1) + f"/api/boards/{board_id}/ws"
    headers = {"Origin": api.url, "Cookie": f"vwk_session={api.session}"}
    async with connect(ws_url, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({"t": "hello", "client_id": str(uuid7()), "last_seq": 0}))
        while json.loads(await ws.recv())["t"] != "welcome":
            pass

        async def drain():
            async for raw in ws:
                t = json.loads(raw)["t"]
                counts[t] = counts.get(t, 0) + 1

        reader = asyncio.create_task(drain())
        ready.set()
        if sender:
            await sender(ws)
        await stop.wait()
        reader.cancel()


async def run(url: str, project: str, env: dict[str, str]) -> dict:
    api = Api(url)
    api.call(
        "POST",
        "/api/auth/login",
        {"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]},
    )
    board = api.call("POST", "/api/boards", {"title": f"mem-check {int(time.time())}"})
    csv = "title\r\n" + "".join(f"card {i}\r\n" for i in range(CARDS))
    api.call("POST", f"/api/boards/{board['id']}/import", csv, "text/csv")
    cards = [c["id"] for c in api.call("GET", f"/api/boards/{board['id']}")["cards"]]
    assert len(cards) == CARDS, len(cards)

    stop, sending = asyncio.Event(), asyncio.Event()
    samples: list[float] = []

    async def send_ops(ws):
        # Only once every client has its welcome: a socket that joins later (hello with
        # last_seq 0) gets no replay and would miss the first events.
        await asyncio.gather(*(r.wait() for r in readies))
        done: dict[str, bool] = {}
        for i in range(OPS_PER_SECOND * SECONDS):
            card = cards[i % CARDS]
            done[card] = not done.get(card, False)
            op = {"id": card, "fields": {"is_done": done[card]}}
            msg = {"t": "op", "op_id": str(uuid7()), "kind": "card.update", "base_seq": 0}
            await ws.send(json.dumps({**msg, "data": op}))
            await asyncio.sleep(1 / OPS_PER_SECOND)
        sending.set()

    readies = [asyncio.Event() for _ in range(CLIENTS)]
    counts: list[dict[str, int]] = [{} for _ in range(CLIENTS)]
    tasks = [
        asyncio.create_task(
            client(api, board["id"], readies[i], stop, send_ops if i == 0 else None, counts[i])
        )
        for i in range(CLIENTS)
    ]
    while not sending.is_set():
        samples.append(await asyncio.to_thread(stack_mb, project))
        await asyncio.sleep(1)
    await asyncio.sleep(1)  # the last acks and events
    stop.set()
    await asyncio.gather(*tasks)
    assert all(r.is_set() for r in readies)
    ops = OPS_PER_SECOND * SECONDS
    if counts[0].get("reject") or counts[0].get("ack", 0) < ops:
        sys.exit(f"the sender's ops weren't all applied: {counts[0]}")
    if any(c.get("event", 0) < ops for c in counts):
        sys.exit(f"a client missed events: {[c.get('event', 0) for c in counts]}")
    api.call("DELETE", f"/api/boards/{board['id']}")
    return {"peak": max(samples), "samples": len(samples)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", required=True, help="the stack's PUBLIC_URL")
    p.add_argument("--project", required=True, help="its compose project name")
    p.add_argument("--env", required=True, help="its .env (admin login)")
    args = p.parse_args()
    env = read_env(args.env)

    idle = max(stack_mb(args.project) for _ in range(3))
    load = asyncio.run(run(args.url.rstrip("/"), args.project, env))
    print(
        f"perf: memory idle {idle:.0f} MiB (limit {IDLE_LIMIT_MB}); {CLIENTS} clients on a "
        f"{CARDS}-card board, {OPS_PER_SECOND} ops/s for {SECONDS} s: peak "
        f"{load['peak']:.0f} MiB over {load['samples']} samples (limit {LOAD_LIMIT_MB})"
    )
    if os.environ.get("VWK_PERF_ENFORCE") == "1":
        failed = []
        if idle >= IDLE_LIMIT_MB:
            failed.append(f"idle {idle:.0f} MiB")
        if load["peak"] >= LOAD_LIMIT_MB:
            failed.append(f"20 clients {load['peak']:.0f} MiB")
        if failed:
            sys.exit("FAIL: " + ", ".join(failed))


if __name__ == "__main__":
    main()
