"""CSV export and import routes (plan §3.1)."""

import re
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from vwkanban.auth.deps import Db
from vwkanban.boards.deps import Member
from vwkanban.csvio.export import export_board

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
