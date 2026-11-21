import pytest
from sqlalchemy import text

from tests.api.helpers import add_user
from tests.api.ops_helpers import PW, login_as


@pytest.fixture(autouse=True)
async def clean_db(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, boards CASCADE"))


@pytest.fixture
async def alice(engine):
    return await add_user(engine, "alice", PW)


@pytest.fixture
async def c(make_client, alice):
    """A client logged in as alice."""
    async with make_client() as client:
        await login_as(client, "alice")
        yield client
