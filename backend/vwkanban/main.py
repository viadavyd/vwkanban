import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from vwkanban.config import get_settings
from vwkanban.db import make_engine, make_sessionmaker

HEALTH_DB_TIMEOUT_S = 2.0

api = APIRouter(prefix="/api")


@api.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    engine = request.app.state.engine
    try:
        async with asyncio.timeout(HEALTH_DB_TIMEOUT_S):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "db": "down"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="VWKanban", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.engine = make_engine(database_url or get_settings().database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.include_router(api)
    return app


app = create_app()
