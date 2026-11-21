import os
from collections.abc import AsyncIterator

import httpx
import pytest

from vwkanban.main import create_app

DEFAULT_TEST_DB = "postgresql+asyncpg://vwkanban:vwkanban@127.0.0.1:5432/vwkanban"


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_TEST_DB)


async def _client(url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await app.state.engine.dispose()


@pytest.fixture
async def client(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(database_url):
        yield c


@pytest.fixture
async def client_db_down() -> AsyncIterator[httpx.AsyncClient]:
    # Port 1 on loopback: nothing listens there, so connects fail fast.
    async for c in _client("postgresql+asyncpg://x:x@127.0.0.1:1/x"):
        yield c
