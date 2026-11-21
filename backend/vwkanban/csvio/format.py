"""CSV format shared by export and import (plan §2 CSV mapping, §3.6).

Columns are the notes' CSV headers, in their order. Text cells use a reversible formula
escape: a cell that a spreadsheet would read as a formula (or that already starts with
the escape character) gets a leading `'` on export, and import strips one. So the cell
is shown as text in Excel/LibreOffice and export → import → export is byte-identical.
"""

import csv
import io
from collections.abc import Iterable

HEADERS = ("id", "title", "status", "date", "parent", "is_done", "tags", "description")
# Cells that go through the formula escape (the others are numbers, dates and booleans).
TEXT_CELLS = ("title", "status", "tags", "description")

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "'")


def escape(value: str) -> str:
    return f"'{value}" if value.startswith(_FORMULA_START) else value


def unescape(value: str) -> str:
    return value[1:] if value.startswith("'") else value


def serialize(rows: Iterable[dict[str, str]]) -> bytes:
    """Rows (header → raw value) as CSV bytes: UTF-8 without a BOM, `\\r\\n` line ends,
    minimal quoting (the csv module's excel dialect). Text cells are escaped here."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, dialect="excel")
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow(escape(row[h]) if h in TEXT_CELLS else row[h] for h in HEADERS)
    return out.getvalue().encode("utf-8")
