import os
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.api.helpers import add_board, add_card, add_user
from tests.conftest import BACKEND_DIR
from vwkanban.ids import uuid7


def test_models_match_migrations(database_url):
    """`alembic check` fails if the models have changes no migration covers."""
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


async def test_child_card_cannot_have_a_status(engine):
    owner = await add_user(engine, "alice", "s3cret-pass")
    board, statuses = await add_board(engine, owner, "B")
    parent = await add_card(engine, board, owner, number=1, status_id=statuses[0])
    with pytest.raises(IntegrityError, match="cards_child_xor_status"):
        await add_card(engine, board, owner, number=2, status_id=statuses[0], parent_id=parent)
    with pytest.raises(IntegrityError, match="cards_child_xor_status"):
        await add_card(engine, board, owner, number=3)


async def test_status_with_cards_cannot_be_deleted(engine):
    owner = await add_user(engine, "alice", "s3cret-pass")
    board, statuses = await add_board(engine, owner, "B")
    await add_card(engine, board, owner, number=1, status_id=statuses[0])
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM statuses WHERE id = :id"), {"id": statuses[0]})


async def test_board_delete_cascades(engine):
    owner = await add_user(engine, "alice", "s3cret-pass")
    board, statuses = await add_board(engine, owner, "B")
    parent = await add_card(engine, board, owner, number=1, status_id=statuses[0])
    await add_card(engine, board, owner, number=2, parent_id=parent)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM boards WHERE id = :id"), {"id": board})
        for table in ("board_members", "statuses", "cards"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


async def test_bad_role_and_color_rejected(engine):
    owner = await add_user(engine, "alice", "s3cret-pass")
    board, _ = await add_board(engine, owner, "B")
    with pytest.raises(IntegrityError, match="board_members_role"):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE board_members SET role = 'viewer' WHERE board_id = :b"), {"b": board}
            )
    with pytest.raises(IntegrityError, match="statuses_color"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO statuses (id, board_id, name, color, position) "
                    "VALUES (:id, :b, 'X', 'cyan', 'a9')"
                ),
                {"id": uuid7(), "b": board},
            )
