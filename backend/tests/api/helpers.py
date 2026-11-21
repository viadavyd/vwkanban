import uuid

from sqlalchemy import text

from vwkanban.auth.passwords import hash_password
from vwkanban.ids import uuid7
from vwkanban.sync.fracindex import key_between


async def add_user(engine, username: str, password: str) -> uuid.UUID:
    h = await hash_password(password)
    user_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, username, password_hash) VALUES (:id, :u, :h)"),
            {"id": user_id, "u": username, "h": h},
        )
    return user_id


async def add_board(
    engine, owner: uuid.UUID, title: str, statuses=("Todo", "Doing", "Done")
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A board owned by `owner`, with one status per name (positions a0, a1, ...)."""
    board_id = uuid7()
    status_ids = [uuid7() for _ in statuses]
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO boards (id, title, created_by) VALUES (:id, :t, :u)"),
            {"id": board_id, "t": title, "u": owner},
        )
        await conn.execute(
            text("INSERT INTO board_members (board_id, user_id, role) VALUES (:b, :u, 'owner')"),
            {"b": board_id, "u": owner},
        )
        for i, (sid, name) in enumerate(zip(status_ids, statuses, strict=True)):
            await conn.execute(
                text(
                    "INSERT INTO statuses (id, board_id, name, color, position) "
                    "VALUES (:id, :b, :n, 'gray', :p)"
                ),
                {"id": sid, "b": board_id, "n": name, "p": f"a{i}"},
            )
    return board_id, status_ids


async def add_member(engine, board_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO board_members (board_id, user_id, role) VALUES (:b, :u, :r)"),
            {"b": board_id, "u": user_id, "r": role},
        )


def nth_key(n: int) -> str:
    """The n-th of a run of increasing fractional keys (a0, a1, ...); valid for any n."""
    key = None
    for _ in range(n + 1):
        key = key_between(key, None)
    return key


async def add_card(
    engine,
    board_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    number: int,
    status_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    is_done: bool = False,
    deleted: bool = False,
) -> uuid.UUID:
    """Inserts a card directly (tests only: the app writes cards through apply_op)."""
    card_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cards (id, board_id, number, parent_card_id, status_id, position,"
                " title, is_done, created_by, deleted_at) VALUES (:id, :b, :n, :p, :s, :pos,"
                " :t, :done, :u, CASE WHEN :deleted THEN now() END)"
            ),
            {
                "id": card_id,
                "b": board_id,
                "n": number,
                "p": parent_id,
                "s": status_id,
                "pos": nth_key(number),
                "t": f"card {number}",
                "done": is_done,
                "u": created_by,
                "deleted": deleted,
            },
        )
    return card_id
