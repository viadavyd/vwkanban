"""CSV import (plan §3.6). Every test that imports also checks export → import (the CSV
round-trip rule): what the board exports after the import imports back unchanged."""

from sqlalchemy import text

from tests.api.helpers import add_user
from tests.api.ops_helpers import PW, create, login_as
from tests.csv.helpers import (
    HEADER,
    export,
    fixture_board,
    import_csv,
    imported,
    new_board,
    rows,
)
from vwkanban.ids import uuid7


async def board_state(engine, board) -> dict:
    async with engine.connect() as conn:
        seq = (
            await conn.execute(text("SELECT seq FROM boards WHERE id = :b"), {"b": board})
        ).scalar_one()
        events = (
            (
                await conn.execute(
                    text("SELECT kind FROM board_events WHERE board_id = :b ORDER BY seq"),
                    {"b": board},
                )
            )
            .scalars()
            .all()
        )
        cards = (
            await conn.execute(text("SELECT count(*) FROM cards WHERE board_id = :b"), {"b": board})
        ).scalar_one()
        statuses = (
            await conn.execute(
                text("SELECT count(*) FROM statuses WHERE board_id = :b"), {"b": board}
            )
        ).scalar_one()
    return {"seq": seq, "events": events, "cards": cards, "statuses": statuses}


async def assert_round_trips(c, board):
    """Export the board, import that into a fresh board, export again: identical."""
    first = await export(c, board)
    copy, _ = await new_board(c, "round-trip copy")
    await imported(c, copy, first)
    assert await export(c, copy) == first


# --- round-trip ------------------------------------------------------------------------


async def test_round_trip_is_byte_identical(c):
    board = await fixture_board(c)
    first = await export(c, board)
    copy, _ = await new_board(c, "Copy")
    result = await imported(c, copy, first)
    assert result["numbers"] == "kept"
    assert result["created"] == 7
    assert result["statuses_created"] == ["Blocked"]
    assert result["warnings"] == []
    assert await export(c, copy) == first
    # and once more, through the copy
    third, _ = await new_board(c, "Copy of copy")
    await imported(c, third, await export(c, copy))
    assert await export(c, third) == first


async def test_kept_numbers_continue_after_the_highest(c):
    board, st = await new_board(c)
    await imported(c, board, HEADER + "3,a,,,,,,\r\n10,b,,,,,,\r\n")
    card = await create(c, board, st["Todo"], "next")
    assert card["number"] == 11
    await assert_round_trips(c, board)


async def test_board_with_only_deleted_cards_renumbers(c, engine):
    board, st = await new_board(c)
    card = await create(c, board, st["Todo"], "gone")
    from tests.api.ops_helpers import send

    assert (await send(c, board, "card.delete", {"id": card["id"]})).status_code == 200
    result = await imported(c, board, HEADER + "1,a,,,,,,\r\n")
    assert result["numbers"] == "renumbered"
    assert [r[0] for r in rows(await export(c, board))] == ["2"]


# --- remap -----------------------------------------------------------------------------


async def test_import_into_non_empty_board_remaps_numbers_and_keeps_parents(c):
    board, st = await new_board(c)
    await create(c, board, st["Todo"], "existing")  # #1
    result = await imported(
        c,
        board,
        HEADER + "1,top,Todo,,,,,\r\n2,kid,,,1,,,\r\n5,other,Doing,,,,,\r\n6,kid2,,,5,,,\r\n",
    )
    assert result["numbers"] == "renumbered"
    out = rows(await export(c, board))
    assert [(r[0], r[1], r[2], r[4]) for r in out] == [
        ("1", "existing", "Todo", ""),
        ("2", "top", "Todo", ""),
        ("3", "kid", "", "2"),
        ("4", "other", "Doing", ""),
        ("5", "kid2", "", "4"),
    ]
    await assert_round_trips(c, board)


async def test_non_numeric_ids_are_renumbered_and_link_parents(c):
    board, _ = await new_board(c)
    result = await imported(c, board, HEADER + "a,top,,,,,,\r\nb,kid,,,a,,,\r\n,loose,,,,,,\r\n")
    assert result["numbers"] == "renumbered"
    out = rows(await export(c, board))
    assert [(r[0], r[1], r[4]) for r in out] == [
        ("1", "top", ""),
        ("2", "kid", "1"),
        ("3", "loose", ""),
    ]
    await assert_round_trips(c, board)


async def test_imported_cards_go_after_existing_ones(c):
    board, st = await new_board(c)
    await create(c, board, st["Todo"], "old")
    await imported(c, board, HEADER + ",new 1,todo,,,,,\r\n,new 2,TODO,,,,,\r\n")
    assert [r[1] for r in rows(await export(c, board))] == ["old", "new 1", "new 2"]


# --- statuses --------------------------------------------------------------------------


async def test_unknown_status_creates_columns_to_the_right(c):
    board, _ = await new_board(c)
    result = await imported(
        c, board, HEADER + "1,a,QA,,,,,\r\n2,b,doing,,,,,\r\n3,c,Ship,,,,,\r\n4,d,qa,,,,,\r\n"
    )
    assert result["statuses_created"] == ["QA", "Ship"]
    statuses = (await c.get(f"/api/boards/{board}")).json()["statuses"]
    ordered = sorted(statuses, key=lambda s: s["position"].encode())
    # After Done (green) come purple, then orange.
    assert [(s["name"], s["color"]) for s in ordered] == [
        ("Todo", "gray"),
        ("Doing", "blue"),
        ("Done", "green"),
        ("QA", "purple"),
        ("Ship", "orange"),
    ]
    out = rows(await export(c, board))
    assert [(r[1], r[2]) for r in out] == [("b", "Doing"), ("a", "QA"), ("d", "QA"), ("c", "Ship")]
    await assert_round_trips(c, board)


async def test_empty_status_goes_to_the_first_column_and_children_ignore_status(c):
    board, _ = await new_board(c)
    await imported(c, board, HEADER + "1,a,,,,,,\r\n2,kid,Nowhere,,1,,,\r\n")
    out = rows(await export(c, board))
    assert [(r[1], r[2], r[4]) for r in out] == [("a", "Todo", ""), ("kid", "", "1")]
    statuses = (await c.get(f"/api/boards/{board}")).json()["statuses"]
    assert "Nowhere" not in {s["name"] for s in statuses}
    await assert_round_trips(c, board)


async def test_board_without_columns_gets_todo(c, engine):
    board, _ = await new_board(c)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM statuses WHERE board_id = :b"), {"b": board})
    result = await imported(c, board, HEADER + "1,a,,,,,,\r\n")
    assert result["statuses_created"] == ["Todo"]
    await assert_round_trips(c, board)


# --- parents ---------------------------------------------------------------------------


async def test_missing_parent_becomes_top_level_with_a_warning(c):
    board, _ = await new_board(c)
    result = await imported(c, board, HEADER + "1,orphan,Doing,,42,,,\r\n")
    assert result["warnings"] == ["row 2: parent '42' not found; imported as a top-level card"]
    assert [(r[1], r[2], r[4]) for r in rows(await export(c, board))] == [("orphan", "Doing", "")]
    await assert_round_trips(c, board)


async def test_depth_error_rolls_back_with_row_numbers(c, engine):
    board, _ = await new_board(c)
    before = await board_state(engine, board)
    r = await import_csv(c, board, HEADER + "1,a,,,,,,\r\n2,b,,,1,,,\r\n3,c,,,2,,,\r\n")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation"
    assert err["rows"] == [
        {"row": 4, "message": "parent '2' is itself a child (cards nest one level)"}
    ]
    assert "row 4" in err["message"]
    assert await board_state(engine, board) == before


# --- all or nothing ----------------------------------------------------------------------


async def test_one_bad_row_rolls_back_everything(c, engine):
    board, _ = await new_board(c)
    await imported(c, board, HEADER + "1,first,,,,,,\r\n")
    before = await board_state(engine, board)
    body = HEADER + "1,good,New column,,,,,\r\n2,bad,,2026-02-30,,,,\r\n3,also bad,,,,maybe,,\r\n"
    r = await import_csv(c, board, body)
    assert r.status_code == 422
    assert [e["row"] for e in r.json()["error"]["rows"]] == [3, 4]
    assert await board_state(engine, board) == before  # no cards, column, seq or event
    await assert_round_trips(c, board)


async def test_failure_while_writing_rolls_back(c, engine, monkeypatch):
    """A failure after rows were inserted (here: the event write) leaves nothing behind."""
    import vwkanban.sync.ops as ops

    board, _ = await new_board(c)
    before = await board_state(engine, board)

    async def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ops, "_commit_event", boom)
    try:
        await import_csv(c, board, HEADER + "1,a,Brand new,,,,,\r\n")
    except RuntimeError:
        pass  # the ASGI transport re-raises the app's exception
    monkeypatch.undo()
    assert await board_state(engine, board) == before


async def test_dry_run_writes_nothing(c, engine):
    board, _ = await new_board(c)
    before = await board_state(engine, board)
    result = await imported(c, board, HEADER + "1,a,QA,,,,,\r\n2,b,,,9,,,\r\n", dry_run=True)
    assert result == {
        "created": 2,
        "statuses_created": ["QA"],
        "numbers": "kept",
        "warnings": ["row 3: parent '9' not found; imported as a top-level card"],
        "seq": None,
    }
    assert await board_state(engine, board) == before


async def test_dry_run_reports_row_errors(c):
    board, _ = await new_board(c)
    r = await import_csv(c, board, HEADER + "1,,,,,,,\r\n", dry_run=True)
    assert r.status_code == 422
    assert r.json()["error"]["rows"] == [{"row": 2, "message": "title is empty"}]


# --- seq, event, field_meta ------------------------------------------------------------


async def test_import_consumes_one_seq_and_logs_board_import(c, engine):
    board, _ = await new_board(c)
    before = await board_state(engine, board)
    client = uuid7()
    result = await imported(c, board, HEADER + "1,a,QA,,,,,\r\n2,b,,,1,,,\r\n", client_id=client)
    after = await board_state(engine, board)
    assert result["seq"] == after["seq"] == before["seq"] + 1
    assert after["events"] == [*before["events"], "board.import"]
    async with engine.connect() as conn:
        payload = (
            await conn.execute(
                text("SELECT payload FROM board_events WHERE board_id = :b AND seq = :s"),
                {"b": board, "s": result["seq"]},
            )
        ).scalar_one()
        metas = (
            (
                await conn.execute(
                    text("SELECT field_meta FROM cards WHERE board_id = :b"), {"b": board}
                )
            )
            .scalars()
            .all()
        )
        status_meta = (
            await conn.execute(
                text("SELECT field_meta FROM statuses WHERE board_id = :b AND name = 'QA'"),
                {"b": board},
            )
        ).scalar_one()
    assert payload["kind"] == "board.import"
    assert payload["client_id"] == str(client)
    assert payload["actor"]["username"] == "alice"
    assert payload["data"] == {"created": 2, "statuses_created": ["QA"]}
    stamp = {"seq": result["seq"], "client": str(client)}
    for meta in metas:
        assert meta["title"] == meta["position"] == meta["is_done"] == stamp
    assert status_meta["name"] == stamp
    await assert_round_trips(c, board)


async def test_imported_text_fields_take_part_in_conflict_checks(c):
    """The import stamps field_meta, so an edit based on a seq before it is a conflict,
    and one based on the import's seq goes through."""
    from tests.api.ops_helpers import send

    board, _ = await new_board(c)
    seq = (await imported(c, board, HEADER + "1,a,,,,,,\r\n"))["seq"]
    card = (await c.get(f"/api/boards/{board}")).json()["cards"][0]
    update = {"id": card["id"], "fields": {"title": "renamed"}}
    r = await send(c, board, "card.update", update, base_seq=seq - 1)
    assert r.status_code == 409, r.text
    r = await send(c, board, "card.update", update, base_seq=seq)
    assert r.status_code == 200, r.text
    await assert_round_trips(c, board)


# --- limits and requests ---------------------------------------------------------------


async def test_body_over_5_mb_is_413(c, engine):
    board, _ = await new_board(c)
    body = HEADER + '1,a,,,,,,"' + "x" * (5 * 1024 * 1024) + '"\r\n'
    r = await import_csv(c, board, body)
    assert r.status_code == 413
    assert r.json()["error"] == {"code": "validation", "message": "file is larger than 5 MB"}
    assert (await board_state(engine, board))["cards"] == 0


async def test_more_than_5000_rows_is_422(c):
    board, _ = await new_board(c)
    body = HEADER + "".join(f"{i},t,,,,,,\r\n" for i in range(1, 5002))
    r = await import_csv(c, board, body)
    assert r.status_code == 422
    assert "more than 5000 rows" in r.json()["error"]["message"]


async def test_5000_rows_import(c):
    board, _ = await new_board(c)
    body = HEADER + "".join(f"{i},card {i},,,,,,\r\n" for i in range(1, 5001))
    assert (await imported(c, board, body))["created"] == 5000
    await assert_round_trips(c, board)


async def test_wrong_content_type_is_415(c):
    board, _ = await new_board(c)
    r = await import_csv(c, board, HEADER, **{"Content-Type": "multipart/form-data"})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "validation"


async def test_import_needs_origin(c, engine):
    board, _ = await new_board(c)
    for origin in ("", "http://evil.example"):
        r = await import_csv(c, board, HEADER + "1,a,,,,,,\r\n", Origin=origin)
        assert r.status_code == 403, origin
    assert (await board_state(engine, board))["cards"] == 0


async def test_editor_can_import_stranger_cannot(c, engine, make_client):
    board, _ = await new_board(c)
    await add_user(engine, "bob", PW)
    async with make_client() as bob:
        await login_as(bob, "bob")
        assert (await import_csv(bob, board, HEADER + "1,a,,,,,,\r\n")).status_code == 404
        r = await c.post(f"/api/boards/{board}/members", json={"username": "bob"})
        assert r.status_code < 300, r.text
        assert (await import_csv(bob, board, HEADER + "1,a,,,,,,\r\n")).status_code == 200
