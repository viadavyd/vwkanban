"""CSV → validated rows (plan §3.6). Pure and synchronous: the route runs `parse` in the
thread pool, then `sync/ops.py::apply_import` writes the rows under the board lock.

Every bad row is reported (with its spreadsheet row number: the header is row 1), so a
file is fixed in one go; any error refuses the whole import.
"""

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field

from pydantic import TypeAdapter, ValidationError

from vwkanban.boards.models import CARD_DESCRIPTION_MAX, STATUS_NAME_MAX
from vwkanban.csvio.format import HEADERS, unescape
from vwkanban.sync.schemas import MAX_TAGS, CardTitle, Tag

MAX_ROWS = 5_000
MAX_BYTES = 5 * 1024 * 1024
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no", ""}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A CSV id that can be kept as the card number (positive, canonical, fits an int4).
_NUMBER = re.compile(r"[1-9]\d{0,8}")
# How many row errors the message spells out (all are in `rows`).
_MESSAGE_ROWS = 5

_title = TypeAdapter(CardTitle)
_tag = TypeAdapter(Tag)


@dataclass
class Row:
    row: int  # spreadsheet row number (header = 1)
    key: str | None  # the CSV id: what `parent` refers to
    title: str
    status: str  # "" = first column (top-level rows); ignored for children
    date: dt.date | None
    is_done: bool
    tags: list[str]
    description: str
    parent_ref: str | None  # the `parent` cell: a CSV id
    parent: int | None = None  # index of the parent row in Parsed.rows


@dataclass
class Parsed:
    rows: list[Row]
    warnings: list[str] = field(default_factory=list)

    @property
    def numbers_keepable(self) -> bool:
        """Every row has an id that can be its card number as-is (plan §3.6)."""
        return all(r.key is not None and _NUMBER.fullmatch(r.key) for r in self.rows)


class ImportInvalid(Exception):
    """The file can't be imported. `rows` lists [{row, message}] (empty for file-level
    problems such as the encoding or a missing header)."""

    def __init__(self, message: str, rows: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.rows = rows or []


def _first_error(e: ValidationError) -> str:
    return str(e.errors()[0]["msg"]).removeprefix("Value error, ").lower()


def _cell(record: list[str], index: dict[str, int], name: str) -> str:
    i = index.get(name)
    return record[i] if i is not None and i < len(record) else ""


def parse(raw: bytes) -> Parsed:
    try:
        text = raw.decode("utf-8-sig")  # a BOM (Excel's UTF-8 CSV) is tolerated
    except UnicodeDecodeError:
        raise ImportInvalid("the file is not UTF-8 text") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if header is None:
            raise ImportInvalid("the file is empty (no header row)")
        names = [h.strip().lower() for h in header]
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        if dupes:
            raise ImportInvalid(f"duplicate column {dupes[0]!r} in the header")
        index = {n: i for i, n in enumerate(names) if n in HEADERS}
        if "title" not in index:
            raise ImportInvalid("the header has no 'title' column")
        warnings = [
            f"column {h.strip()!r} is not a card field; ignored"
            for h, n in zip(header, names, strict=True)
            if n not in HEADERS
        ]
        rows: list[Row] = []
        errors: list[dict] = []
        for number, record in enumerate(reader, start=2):
            if not any(cell.strip() for cell in record):
                continue  # blank line
            if len(rows) + len(errors) >= MAX_ROWS:
                raise ImportInvalid(f"the file has more than {MAX_ROWS} rows")
            try:
                rows.append(_row(number, record, index))
            except ValueError as e:
                errors.append({"row": number, "message": str(e)})
    except csv.Error as e:
        raise ImportInvalid(f"row {reader.line_num}: {e}") from None
    errors.extend(_link_parents(rows, warnings))
    if errors:
        errors.sort(key=lambda e: e["row"])
        shown = "; ".join(f"row {e['row']}: {e['message']}" for e in errors[:_MESSAGE_ROWS])
        more = f" (and {len(errors) - _MESSAGE_ROWS} more)" if len(errors) > _MESSAGE_ROWS else ""
        raise ImportInvalid(f"nothing imported, {len(errors)} bad rows: {shown}{more}", errors)
    return Parsed(rows, warnings)


def _row(number: int, record: list[str], index: dict[str, int]) -> Row:
    def cell(name: str) -> str:
        return _cell(record, index, name)

    problems = []
    title = ""
    try:
        title = _title.validate_python(unescape(cell("title")))
    except ValidationError as e:
        problems.append(
            "title is empty" if not cell("title").strip() else f"title: {_first_error(e)}"
        )

    status = unescape(cell("status")).strip()
    if len(status) > STATUS_NAME_MAX:
        problems.append(f"status is longer than {STATUS_NAME_MAX} characters")

    date = None
    if raw_date := cell("date").strip():
        try:
            if not _DATE.fullmatch(raw_date):
                raise ValueError
            date = dt.date.fromisoformat(raw_date)
        except ValueError:
            problems.append(f"date {raw_date!r} is not YYYY-MM-DD")

    flag = cell("is_done").strip().lower()
    if flag not in _TRUE | _FALSE:
        problems.append(f"is_done {cell('is_done').strip()!r} is not true/false/1/0/yes/no")

    tags: list[str] = []
    for part in unescape(cell("tags")).split(";"):
        if not part.strip():
            continue
        try:
            tag = _tag.validate_python(part)
        except ValidationError as e:
            problems.append(f"tag {part.strip()!r}: {_first_error(e)}")
            continue
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        problems.append(f"more than {MAX_TAGS} tags")

    description = unescape(cell("description"))
    if len(description) > CARD_DESCRIPTION_MAX:
        problems.append(f"description is longer than {CARD_DESCRIPTION_MAX} characters")

    if problems:
        raise ValueError("; ".join(problems))
    return Row(
        row=number,
        key=cell("id").strip() or None,
        title=title,
        status=status,
        date=date,
        is_done=flag in _TRUE,
        tags=tags,
        description=description,
        parent_ref=cell("parent").strip() or None,
    )


def _link_parents(rows: list[Row], warnings: list[str]) -> list[dict]:
    """Resolves `parent` within the file (plan §3.6): a missing parent makes the row
    top-level (warning); a parent that is itself a child is an error (depth 1)."""
    errors = []
    by_key: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.key is None:
            continue
        if r.key in by_key:
            errors.append({"row": r.row, "message": f"id {r.key!r} is used twice"})
        else:
            by_key[r.key] = i
    parents: dict[int, int] = {}
    for i, r in enumerate(rows):
        ref = r.parent_ref
        if ref is None:
            continue
        if ref == r.key:
            errors.append({"row": r.row, "message": "a card can't be its own parent"})
        elif ref not in by_key:
            warnings.append(f"row {r.row}: parent {ref!r} not found; imported as a top-level card")
        else:
            parents[i] = by_key[ref]
    for i, p in parents.items():
        if p in parents:
            errors.append(
                {
                    "row": rows[i].row,
                    "message": f"parent {rows[p].key!r} is itself a child (cards nest one level)",
                }
            )
        else:
            rows[i].parent = p
    return errors
