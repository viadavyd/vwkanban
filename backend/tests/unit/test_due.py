import datetime as dt

import pytest

from vwkanban.boards.due import format_due, normalize_due, parse_due


def test_parse_and_format():
    assert parse_due("2026-11-30") == (dt.date(2026, 11, 30), None)
    assert parse_due(" 2026-11-30 14:30 ") == (dt.date(2026, 11, 30), dt.time(14, 30))
    assert normalize_due("2026-11-30T00:00") == "2026-11-30 00:00"
    assert format_due(None, None) is None
    assert format_due(dt.date(2026, 1, 2), dt.time(9, 5)) == "2026-01-02 09:05"


@pytest.mark.parametrize("bad", ["", "2026-02-30", "2026-11-30 24:00", "2026-11-30 12:60", "x"])
def test_invalid(bad):
    with pytest.raises(ValueError, match="YYYY-MM-DD HH:MM"):
        parse_due(bad)
