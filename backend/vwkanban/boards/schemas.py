import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from vwkanban.boards.models import BOARD_TITLE_MAX

BoardTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BOARD_TITLE_MAX)
]


class BoardIn(BaseModel):
    title: BoardTitle


class StatusCount(BaseModel):
    name: str
    color: str
    count: int


class Summary(BaseModel):
    total: int
    done: int
    by_status: list[StatusCount]


class DashboardItem(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: dt.datetime
    role: str
    summary: Summary


class BoardOut(BaseModel):
    id: uuid.UUID
    title: str
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class StatusOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    position: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str


class BoardDetail(BaseModel):
    board: BoardOut
    seq: int
    statuses: list[StatusOut]
    cards: list[dict]  # filled from M3a
    members: list[MemberOut]
