import uuid

from vwkanban.ids import uuid7

PW = "s3cret-pass"


async def login_as(c, username: str) -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


def op_body(kind: str, data: dict, *, client_id=None, op_id=None, base_seq: int = 0) -> dict:
    return {
        "client_id": str(client_id or uuid7()),
        "op": {
            "op_id": str(op_id or uuid7()),
            "kind": kind,
            "base_seq": base_seq,
            "data": {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()},
        },
    }


async def send(c, board, kind: str, data: dict, **kw):
    return await c.post(f"/api/boards/{board}/ops", json=op_body(kind, data, **kw))


async def create(c, board, status_id, title="card", *, after=None, before=None, **kw) -> dict:
    """card.create; returns the created card (asserts the ack)."""
    data = {"id": uuid7(), "status_id": status_id, "title": title}
    if after:
        data["after_id"] = after
    if before:
        data["before_id"] = before
    r = await send(c, board, "card.create", data, **kw)
    assert r.status_code == 200, r.text
    return r.json()["event"]["data"]["card"]


async def column_titles(c, board, status_id) -> list[str]:
    cards = (await c.get(f"/api/boards/{board}")).json()["cards"]
    col = [x for x in cards if x["status_id"] == str(status_id)]
    return [x["title"] for x in sorted(col, key=lambda x: x["position"].encode())]
