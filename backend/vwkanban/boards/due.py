"""A card's due value (plan §2): a date with an optional wall-clock time, no timezone.

The text form, used on the wire, in CSV and in the editor, is `YYYY-MM-DD` or
`YYYY-MM-DD HH:MM` (a `T` separator is accepted and normalised to a space). It is stored
as `cards.date` + `cards.due_time`.
"""

import datetime as dt
import re

_DUE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2}))?")
FORMAT_HINT = "YYYY-MM-DD or YYYY-MM-DD HH:MM"


def parse_due(text: str) -> tuple[dt.date, dt.time | None]:
    """Raises ValueError if `text` isn't a valid due value."""
    m = _DUE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"the due date is {FORMAT_HINT}")
    try:
        day = dt.date.fromisoformat(m[1])
        time = dt.time(int(m[2]), int(m[3])) if m[2] else None
    except ValueError:
        raise ValueError(f"the due date is {FORMAT_HINT}") from None
    return day, time


def format_due(day: dt.date | None, time: dt.time | None) -> str | None:
    if day is None:
        return None
    return f"{day.isoformat()} {time:%H:%M}" if time is not None else day.isoformat()


def normalize_due(text: str) -> str:
    return format_due(*parse_due(text))  # type: ignore[return-value]
