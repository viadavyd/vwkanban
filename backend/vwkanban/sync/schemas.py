"""Op envelopes (plan §3.2). One model per kind, discriminated on `kind`.

M3a: card.create (top-level), card.update (is_done), card.delete.
M3b: card.move, card.restore, pasted children on card.create, `undo`, status.*.
Text-field updates and child create/reorder arrive in M5.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from vwkanban.boards.models import CARD_DESCRIPTION_MAX, CARD_TITLE_MAX, COLORS, STATUS_NAME_MAX

CardTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CARD_TITLE_MAX)
]
StatusName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=STATUS_NAME_MAX)
]
Color = Literal[COLORS]  # type: ignore[valid-type]
Tag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30, pattern=r"^[^;]*$"),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Children pasted with their parent (`p` of a copied card); depth 1, so no grandchildren.
MAX_PASTED_CHILDREN = 100


class ChildData(_Strict):
    id: uuid.UUID
    title: CardTitle
    description: str = Field(default="", max_length=CARD_DESCRIPTION_MAX)
    tags: list[Tag] = []
    date: dt.date | None = None
    is_done: bool = False


class CardCreateData(ChildData):
    status_id: uuid.UUID
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
    children: list[ChildData] = Field(default=[], max_length=MAX_PASTED_CHILDREN)


class CardFields(_Strict):
    is_done: bool  # text fields (with their conflict check) arrive in M5


class CardUpdateData(_Strict):
    id: uuid.UUID
    fields: CardFields


class CardDeleteData(_Strict):
    id: uuid.UUID


class CardMoveData(_Strict):
    id: uuid.UUID
    status_id: uuid.UUID  # parent_id (child reorder) is deferred after the MVP
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class StatusCreateData(_Strict):
    id: uuid.UUID
    name: StatusName
    color: Color
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class StatusUpdateData(_Strict):
    id: uuid.UUID
    name: StatusName | None = None
    color: Color | None = None

    @model_validator(mode="after")
    def _some_field(self):
        if self.name is None and self.color is None:
            raise ValueError("name or color is required")
        return self


class StatusMoveData(_Strict):
    id: uuid.UUID
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class StatusDeleteData(_Strict):
    id: uuid.UUID


class _OpBase(_Strict):
    op_id: uuid.UUID
    # For undo: the seq of the op being undone (the undo check compares field_meta to it).
    base_seq: int = Field(ge=0)
    undo: bool = False


class CardCreate(_OpBase):
    kind: Literal["card.create"]
    data: CardCreateData


class CardUpdate(_OpBase):
    kind: Literal["card.update"]
    data: CardUpdateData


class CardDelete(_OpBase):
    kind: Literal["card.delete"]
    data: CardDeleteData


class CardMove(_OpBase):
    kind: Literal["card.move"]
    data: CardMoveData


class CardRestore(_OpBase):
    """Undo of a delete only."""

    kind: Literal["card.restore"]
    data: CardDeleteData

    @model_validator(mode="after")
    def _only_as_undo(self):
        if not self.undo:
            raise ValueError("card.restore is only sent as an undo")
        return self


class StatusCreate(_OpBase):
    kind: Literal["status.create"]
    data: StatusCreateData


class StatusUpdate(_OpBase):
    kind: Literal["status.update"]
    data: StatusUpdateData


class StatusMove(_OpBase):
    kind: Literal["status.move"]
    data: StatusMoveData


class StatusDelete(_OpBase):
    kind: Literal["status.delete"]
    data: StatusDeleteData


Op = Annotated[
    CardCreate
    | CardUpdate
    | CardDelete
    | CardMove
    | CardRestore
    | StatusCreate
    | StatusUpdate
    | StatusMove
    | StatusDelete,
    Field(discriminator="kind"),
]


class OpRequest(_Strict):
    client_id: uuid.UUID
    op: Op


class Ack(BaseModel):
    t: Literal["ack"] = "ack"
    op_id: uuid.UUID
    seq: int
    event: dict[str, Any]  # {seq, op_id, client_id, actor, kind, data}
