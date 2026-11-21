import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from vwkanban.config import Settings
from vwkanban.main import create_app

DEFAULT_TEST_DB = "postgresql+asyncpg://vwkanban:vwkanban@127.0.0.1:5432/vwkanban"
BACKEND_DIR = Path(__file__).resolve().parent.parent
PUBLIC_URL = "http://vwk.test"

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_TEST_DB)


@pytest.fixture(scope="session", autouse=True)
def migrated(database_url: str) -> None:
    """Brings the test DB to head once per run (a subprocess: Alembic's env runs its own loop)."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url)
    yield eng
    await eng.dispose()


def make_settings(database_url: str, **overrides) -> Settings:
    base = {
        "DATABASE_URL": database_url,
        "public_url": PUBLIC_URL,
        "allow_signup": False,
        "admin_username": None,
        "admin_password": None,
        "cookie_secure": None,
    }
    # _env_file=None: tests never read a developer's .env.
    return Settings(_env_file=None, **{**base, **overrides})


@asynccontextmanager
async def _client(settings: Settings, origin: str | None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    headers = {"Origin": origin} if origin else {}
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL, headers=headers) as c:
        c.app = app  # type: ignore[attr-defined]
        yield c
    await app.state.engine.dispose()


@pytest.fixture
def make_client(database_url: str) -> ClientFactory:
    """`async with make_client(allow_signup=True) as c:` — an app with settings overrides.
    The client sends `Origin: PUBLIC_URL` unless `origin=` says otherwise."""

    def factory(origin: str | None = PUBLIC_URL, **overrides) -> AbstractAsyncContextManager:
        return _client(make_settings(database_url, **overrides), origin)

    return factory


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client() as c:
        yield c


@pytest.fixture
async def client_db_down(database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    # Port 1 on loopback: nothing listens there, so connects fail fast.
    settings = make_settings("postgresql+asyncpg://x:x@127.0.0.1:1/x")
    async with _client(settings, PUBLIC_URL) as c:
        yield c
