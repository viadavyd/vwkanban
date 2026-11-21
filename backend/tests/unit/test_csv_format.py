import csv
import io

import pytest

from vwkanban.csvio.format import HEADERS, escape, serialize, unescape


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+1", "-minus", "@at", "\tTab", "\rCR", "'quoted", "''two"],
)
def test_formula_start_is_escaped_and_reversible(value):
    assert escape(value) == "'" + value
    assert unescape(escape(value)) == value


@pytest.mark.parametrize("value", ["", "plain", "a=b", "1-2", " lead space", "ü"])
def test_plain_values_are_unchanged(value):
    assert escape(value) == value
    assert unescape(escape(value)) == value


def _row(**kw):
    return {h: kw.get(h, "") for h in HEADERS}


def test_serialize_quotes_and_line_ends():
    out = serialize([_row(id="1", title='a, "b"', description="x\r\ny\nz", tags="=t")])
    assert out == (
        b"id,title,status,date,parent,is_done,tags,description\r\n"
        b'1,"a, ""b""",,,,,\'=t,"x\r\ny\nz"\r\n'
    )


def test_serialize_reads_back_with_the_csv_module():
    rows = [_row(id="7", title="日本語", description='multi\nline, "q"', status="-x")]
    text = serialize(rows).decode("utf-8")
    back = list(csv.reader(io.StringIO(text, newline="")))
    assert back[0] == list(HEADERS)
    assert back[1][1] == "日本語"
    assert back[1][2] == "'-x"
    assert back[1][7] == 'multi\nline, "q"'
