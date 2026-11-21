"""Op envelopes (plan §3.2). One model per kind, discriminated on `kind`.

M3a kinds: card.create (top-level), card.update (is_done), card.delete. Children,
text-field updates, moves, restore, undo and status ops arrive in later milestones.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from vwkanban.boards.models import CARD_DESCRIPTION_MAX, CARD_TITLE_MAX

CardTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CARD_TITLE_MAX)
]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30, pattern=r"^[^;]*$"),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardCreateData(_Strict):
    id: uuid.UUID
    status_id: uuid.UUID
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
    title: CardTitle
    description: str = Field(default="", max_length=CARD_DESCRIPTION_MAX)
    tags: list[Tag] = []
    date: dt.date | None = None
    is_done: bool = False


class CardFields(_Strict):
    is_done: bool  # text fields (with their conflict check) arrive in M5


class CardUpdateData(_Strict):
    id: uuid.UUID
    fields: CardFields


class CardDeleteData(_Strict):
    id: uuid.UUID


class _OpBase(_Strict):
    op_id: uuid.UUID
    base_seq: int = Field(ge=0)


class CardCreate(_OpBase):
    kind: Literal["card.create"]
    data: CardCreateData


class CardUpdate(_OpBase):
    kind: Literal["card.update"]
    data: CardUpdateData


class CardDelete(_OpBase):
    kind: Literal["card.delete"]
    data: CardDeleteData


Op = Annotated[CardCreate | CardUpdate | CardDelete, Field(discriminator="kind")]


class OpRequest(_Strict):
    client_id: uuid.UUID
    op: Op


class Ack(BaseModel):
    t: Literal["ack"] = "ack"
    op_id: uuid.UUID
    seq: int
    event: dict[str, Any]  # {seq, op_id, client_id, actor, kind, data}
