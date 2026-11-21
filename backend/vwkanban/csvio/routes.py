"""CSV export and import routes (plan §3.1)."""

import re
import uuid
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from vwkanban.auth.deps import Db
from vwkanban.boards.deps import Member
from vwkanban.csvio.export import export_board
from vwkanban.csvio.import_ import MAX_BYTES, ImportInvalid, parse
from vwkanban.errors import ApiError
from vwkanban.ids import uuid7
from vwkanban.sync.ops import apply_import

router = APIRouter(prefix="/boards", tags=["csv"])


def _filename(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.") or "board"


@router.get("/{board_id}/export.csv", response_class=Response)
async def export_csv(member: Member, db: Db) -> Response:
    body = await export_board(db, member.board.id)
    title = member.board.title
    disposition = (
        f"attachment; filename=\"{_filename(title)}.csv\"; filename*=UTF-8''{quote(title)}.csv"
    )
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )


class ImportResult(BaseModel):
    created: int
    statuses_created: list[str]  # names of the columns the import added
    numbers: str  # "kept" (CSV ids are the card numbers) or "renumbered"
    warnings: list[str]
    seq: int | None  # the board.import event's seq; null on a dry run


async def _read_body(request: Request) -> bytes:
    """The raw CSV body, refused as soon as it passes MAX_BYTES (nginx caps it a little
    higher and answers with the same envelope)."""
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind != "text/csv":
        raise ApiError(415, "validation", "send the file as a text/csv body")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise ApiError(413, "validation", "file is larger than 5 MB")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/{board_id}/import")
async def import_csv(
    member: Member,
    db: Db,
    request: Request,
    dry_run: bool = False,
    client_id: uuid.UUID | None = None,
) -> ImportResult:
    """Appends the file's cards (plan §3.6), all or nothing, as one `board.import` event.
    `dry_run=1` validates and reports the same counts without writing (the `I` preview)."""
    raw = await _read_body(request)
    try:
        parsed = await anyio.to_thread.run_sync(parse, raw)
    except ImportInvalid as e:
        raise ApiError(422, "validation", e.message, {"rows": e.rows}) from None
    result = await apply_import(
        db, member, client_id or uuid7(), parsed, dry_run=dry_run, hub=request.app.state.hub
    )
    return ImportResult(**result)
