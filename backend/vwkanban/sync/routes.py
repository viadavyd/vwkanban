from fastapi import APIRouter

from vwkanban.auth.deps import Db
from vwkanban.boards.deps import Member
from vwkanban.sync.ops import apply_op
from vwkanban.sync.schemas import Ack, OpRequest

router = APIRouter(prefix="/boards", tags=["sync"])


@router.post("/{board_id}/ops")
async def post_op(body: OpRequest, member: Member, db: Db) -> Ack:
    """Same handler as a WebSocket `op` (M4). Ack: 200; reject: the error envelope with
    `op_id` and `current` (the entity's server state, or null)."""
    return await apply_op(db, member, body.client_id, body.op)
