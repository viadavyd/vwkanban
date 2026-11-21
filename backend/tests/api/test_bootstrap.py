from sqlalchemy import text

from tests.api.helpers import add_user
from tests.conftest import make_settings
from vwkanban.auth.bootstrap import ensure_admin
from vwkanban.db import make_engine, make_sessionmaker


async def _ensure(database_url, **overrides) -> bool:
    engine = make_engine(database_url)
    try:
        return await ensure_admin(
            make_sessionmaker(engine), make_settings(database_url, **overrides)
        )
    finally:
        await engine.dispose()


async def usernames(engine) -> list[str]:
    async with engine.connect() as conn:
        return list((await conn.execute(text("SELECT username FROM users"))).scalars())


async def test_admin_created_once_on_empty_db(database_url, engine):
    creds = {"admin_username": "Admin", "admin_password": "change-me-too"}
    assert await _ensure(database_url, **creds) is True
    assert await _ensure(database_url, **creds) is False
    assert await usernames(engine) == ["admin"]


async def test_admin_skipped_when_users_exist(database_url, engine):
    await add_user(engine, "alice", "s3cret-pass")
    assert await _ensure(database_url, admin_username="admin", admin_password="x" * 10) is False
    assert await usernames(engine) == ["alice"]


async def test_admin_skipped_without_credentials_or_with_bad_ones(database_url, engine):
    assert await _ensure(database_url) is False
    assert await _ensure(database_url, admin_username="admin", admin_password="short") is False
    assert await usernames(engine) == []


async def test_admin_can_log_in(database_url, make_client):
    await _ensure(database_url, admin_username="admin", admin_password="change-me-too")
    async with make_client() as c:
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "change-me-too"})
    assert r.status_code == 200
