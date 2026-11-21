"""A fixture board for CSV tests, built through the API (as the app writes it)."""

from tests.api.ops_helpers import create, send
from vwkanban.ids import uuid7

# Description with everything CSV has to quote: commas, quotes, CRLF and LF newlines.
TRICKY_DESCRIPTION = 'Line one, with "quotes"\r\nline two\nline three: a,b,"c"'


async def new_board(c, title="CSV board") -> tuple[str, dict[str, str]]:
    """A fresh board (seeded Todo / Doing / Done); returns its id and {name: status id}."""
    r = await c.post("/api/boards", json={"title": title})
    assert r.status_code == 201, r.text
    board = r.json()["id"]
    statuses = (await c.get(f"/api/boards/{board}")).json()["statuses"]
    return board, {s["name"]: s["id"] for s in statuses}


async def fixture_board(c) -> str:
    """Seed columns plus a custom one at the right; children; unicode tags; a tricky
    description; dates set and empty; formula-like text; a gap in the card numbers."""
    board, st = await new_board(c, "Fixture ✓")
    blocked = str(uuid7())
    r = await send(
        c,
        board,
        "status.create",
        {"id": blocked, "name": "Blocked", "color": "red", "after_id": st["Done"]},
    )
    assert r.status_code == 200, r.text
    st["Blocked"] = blocked

    async def card(status, title, **fields):
        data = {"id": str(uuid7()), "status_id": status, "title": title, **fields}
        r = await send(c, board, "card.create", data)
        assert r.status_code == 200, r.text
        return r.json()["event"]["data"]["card"]

    await card(
        st["Todo"],
        "Plan the hackathon",
        description=TRICKY_DESCRIPTION,
        tags=["ünïcode", "日本語", "-minus"],
        date="2026-12-01",
        children=[
            {"id": str(uuid7()), "title": "Book a room", "is_done": True},
            {"id": str(uuid7()), "title": '=HYPERLINK("x")', "tags": ["@at"]},
        ],
    )
    gone = await card(st["Todo"], "Deleted later")
    assert (await send(c, board, "card.delete", {"id": gone["id"]})).status_code == 200
    await card(st["Todo"], "+1 for pizza", is_done=True, tags=["food"])
    await card(st["Doing"], "'quoted' start", description="\tindented with a tab")
    await card(st["Blocked"], 'Waiting on API, "keys"', date="2027-01-31")
    await create(c, board, st["Done"], "Done thing")
    return board


async def export(c, board) -> bytes:
    r = await c.get(f"/api/boards/{board}/export.csv")
    assert r.status_code == 200, r.text
    return r.content


async def import_csv(c, board, body: bytes | str, *, dry_run=False, client_id=None, **headers):
    if isinstance(body, str):
        body = body.encode("utf-8")
    params = {"dry_run": "1"} if dry_run else {}
    if client_id:
        params["client_id"] = str(client_id)
    return await c.post(
        f"/api/boards/{board}/import",
        content=body,
        params=params,
        headers={"Content-Type": "text/csv", **headers},
    )


async def imported(c, board, body, **kw) -> dict:
    r = await import_csv(c, board, body, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def rows(data: bytes) -> list[list[str]]:
    import csv
    import io

    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))[1:]


HEADER = "id,title,status,date,parent,is_done,tags,description\r\n"
