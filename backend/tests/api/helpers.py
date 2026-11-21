from sqlalchemy import text

from vwkanban.auth.passwords import hash_password
from vwkanban.ids import uuid7


async def add_user(engine, username: str, password: str) -> None:
    h = await hash_password(password)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, username, password_hash) VALUES (:id, :u, :h)"),
            {"id": uuid7(), "u": username, "h": h},
        )
