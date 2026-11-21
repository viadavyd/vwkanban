import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from vwkanban.auth.bootstrap import ensure_admin
from vwkanban.auth.origin import check_origin
from vwkanban.auth.routes import router as auth_router
from vwkanban.auth.sessions import purge_expired
from vwkanban.boards.routes import router as boards_router
from vwkanban.config import Settings, get_settings
from vwkanban.db import make_engine, make_sessionmaker
from vwkanban.errors import install_error_handlers

HEALTH_DB_TIMEOUT_S = 2.0

health = APIRouter()


@health.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    engine = request.app.state.engine
    try:
        async with asyncio.timeout(HEALTH_DB_TIMEOUT_S):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "db": "down"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})


def build_api_router() -> APIRouter:
    # The Origin check covers every state-changing route under /api.
    api = APIRouter(prefix="/api", dependencies=[Depends(check_origin)])
    api.include_router(health)
    api.include_router(auth_router)
    api.include_router(boards_router)
    return api


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with app.state.sessionmaker() as db:
            await purge_expired(db)
        await ensure_admin(app.state.sessionmaker, settings)
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="VWKanban", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    install_error_handlers(app)
    app.include_router(build_api_router())
    return app


app = create_app()
