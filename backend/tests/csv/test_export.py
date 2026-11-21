from tests.api.ops_helpers import login_as
from tests.csv.helpers import export, fixture_board, new_board


async def test_export_order_children_and_escape(c):
    board = await fixture_board(c)
    body = await export(c, board)
    assert (
        body
        == (
            "id,title,status,date,parent,is_done,tags,description\r\n"
            "1,Plan the hackathon,Todo,2026-12-01,,false,ünïcode;日本語;-minus,"
            '"Line one, with ""quotes""\r\nline two\nline three: a,b,""c"""\r\n'
            "2,Book a room,,,1,true,,\r\n"
            '3,"\'=HYPERLINK(""x"")",,,1,false,\'@at,\r\n'
            "5,'+1 for pizza,Todo,,,true,food,\r\n"
            "6,''quoted' start,Doing,,,false,,'\tindented with a tab\r\n"
            "8,Done thing,Done,,,false,,\r\n"
            '7,"Waiting on API, ""keys""",Blocked,2027-01-31,,false,,\r\n'
        ).encode()
    )


async def test_export_headers(c):
    board = await fixture_board(c)
    r = await c.get(f"/api/boards/{board}/export.csv")
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"Fixture.csv\"; filename*=UTF-8''Fixture%20%E2%9C%93.csv"
    )
    assert not r.content.startswith(b"\xef\xbb\xbf")  # no BOM


async def test_export_empty_board_is_just_the_header(c):
    board, _ = await new_board(c)
    assert await export(c, board) == b"id,title,status,date,parent,is_done,tags,description\r\n"


async def test_export_needs_membership(c, make_client, engine):
    from tests.api.helpers import add_user
    from tests.api.ops_helpers import PW

    board = await fixture_board(c)
    await add_user(engine, "mallory", PW)
    async with make_client() as m:
        await login_as(m, "mallory")
        r = await m.get(f"/api/boards/{board}/export.csv")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
