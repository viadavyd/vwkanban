import datetime as dt

import pytest

from vwkanban.csvio.import_ import MAX_ROWS, ImportInvalid, parse

HEADER = "id,title,status,date,parent,is_done,tags,description\r\n"


def csv_bytes(*lines: str, header: str = HEADER) -> bytes:
    return (header + "".join(line + "\r\n" for line in lines)).encode("utf-8")


def invalid(raw: bytes) -> ImportInvalid:
    with pytest.raises(ImportInvalid) as e:
        parse(raw)
    return e.value


def test_full_row():
    (r,) = parse(csv_bytes('7,Hello,Doing,2026-12-01,,true,a; b ;;a,"multi\r\nline"')).rows
    assert (r.row, r.key, r.title, r.status) == (2, "7", "Hello", "Doing")
    assert r.date == dt.date(2026, 12, 1) and r.time is None
    assert r.is_done is True
    assert r.tags == ["a", "b"]  # trimmed, empties dropped, duplicates removed
    assert r.description == "multi\r\nline"
    assert r.parent is None


def test_bom_is_tolerated():
    (r,) = parse(b"\xef\xbb\xbf" + csv_bytes("1,x,,,,,,")).rows
    assert r.title == "x"


@pytest.mark.parametrize(
    ("value", "done"),
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("Yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
    ],
)
def test_is_done_spellings(value, done):
    assert parse(csv_bytes(f"1,x,,,,{value},,")).rows[0].is_done is done


@pytest.mark.parametrize(
    "value",
    [
        "2026-13-01",
        "2026-02-30",
        "01/12/2026",
        "2026-1-1",
        "x",
        "2026-12-01 25:00",
        "2026-12-01 9:30",
    ],
)
def test_bad_dates(value):
    e = invalid(csv_bytes(f"1,x,,{value},,,,"))
    msg = f"date {value!r} is not YYYY-MM-DD or YYYY-MM-DD HH:MM"
    assert e.rows == [{"row": 2, "message": msg}]


@pytest.mark.parametrize("value", ["2026-12-01 14:30", "2026-12-01T14:30"])
def test_date_with_time(value):
    (r,) = parse(csv_bytes(f"1,x,,{value},,,,")).rows
    assert (r.date, r.time) == (dt.date(2026, 12, 1), dt.time(14, 30))


def test_escapes_are_stripped():
    (r,) = parse(csv_bytes("1,'=1+1,'-x,,,,'@a;b,'\tdesc")).rows
    assert (r.title, r.status, r.tags, r.description) == ("=1+1", "-x", ["@a", "b"], "\tdesc")


def test_headers_any_order_and_case_and_only_title_required():
    (r,) = parse(csv_bytes("Hi,yes", header="Title,IS_DONE\r\n")).rows
    assert (r.key, r.title, r.is_done, r.status, r.tags) == (None, "Hi", True, "", [])


def test_unknown_header_warns():
    parsed = parse(csv_bytes("x,y", header="title,owner\r\n"))
    assert parsed.warnings == ["column 'owner' is not a card field; ignored"]


def test_missing_title_header():
    assert invalid(csv_bytes("1", header="id\r\n")).message == "the header has no 'title' column"


def test_empty_file_and_not_utf8():
    assert "empty" in invalid(b"").message
    assert "UTF-8" in invalid(b"title\r\n\xff\xfe\r\n").message


def test_blank_lines_are_skipped():
    assert [r.title for r in parse(csv_bytes("1,a,,,,,,", "", ",,,,,,,", "2,b,,,,,,")).rows] == [
        "a",
        "b",
    ]


def test_bad_title_tag_and_flag_on_one_row():
    e = invalid(csv_bytes(f"1,,,,,maybe,{'t' * 31},"))
    (err,) = e.rows
    assert err["row"] == 2
    assert "title is empty" in err["message"]
    assert "is_done 'maybe'" in err["message"]
    assert "tag" in err["message"]


def test_duplicate_ids():
    e = invalid(csv_bytes("1,a,,,,,,", "1,b,,,,,,"))
    assert e.rows == [{"row": 3, "message": "id '1' is used twice"}]


def test_parents_resolve_in_either_order():
    parsed = parse(csv_bytes("2,kid,,,1,,,", "1,top,Todo,,,,,"))
    kid, top = parsed.rows
    assert kid.parent == 1 and top.parent is None


def test_self_parent_is_an_error():
    assert invalid(csv_bytes("1,a,,,1,,,")).rows == [
        {"row": 2, "message": "a card can't be its own parent"}
    ]


def test_parent_that_is_a_child_is_a_depth_error():
    e = invalid(csv_bytes("1,top,,,,,,", "2,kid,,,1,,,", "3,grandkid,,,2,,,"))
    assert e.rows == [{"row": 4, "message": "parent '2' is itself a child (cards nest one level)"}]


def test_missing_parent_becomes_top_level_with_a_warning():
    parsed = parse(csv_bytes("2,orphan,Doing,,99,,,"))
    assert parsed.rows[0].parent is None
    assert parsed.warnings == ["row 2: parent '99' not found; imported as a top-level card"]


def test_all_bad_rows_are_reported_and_in_the_message():
    e = invalid(csv_bytes("1,a,,bad,,,,", "2,ok,,,,,,", "3,c,,,,nope,,"))
    assert [r["row"] for r in e.rows] == [2, 4]
    assert e.message.startswith("nothing imported, 2 bad rows: row 2: date")


def test_too_many_rows():
    rows = [f"{i},t,,,,,," for i in range(1, MAX_ROWS + 2)]
    assert "more than 5000 rows" in invalid(csv_bytes(*rows)).message
    assert len(parse(csv_bytes(*rows[:MAX_ROWS])).rows) == MAX_ROWS


def test_numbers_keepable():
    assert parse(csv_bytes("1,a,,,,,,", "12,b,,,,,,")).numbers_keepable
    for ids in (["1", ""], ["0"], ["01"], ["x"], ["-1"], ["1234567890"]):
        lines = [f"{i},t{n},,,,,," for n, i in enumerate(ids)]
        assert not parse(csv_bytes(*lines)).numbers_keepable, ids


def test_long_status_and_description():
    e = invalid(csv_bytes(f"1,a,{'s' * 41},,,,,{'d' * 20_001}"))
    assert "status is longer than 40" in e.rows[0]["message"]
    assert "description is longer than 20000" in e.rows[0]["message"]
