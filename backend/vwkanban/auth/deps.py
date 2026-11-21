from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.auth.models import User
from vwkanban.auth.sessions import COOKIE_NAME, resolve_session, set_session_cookie
from vwkanban.config import Settings
from vwkanban.errors import ApiError


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as db:
        yield db


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


Db = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]


async def current_user(request: Request, response: Response, db: Db, settings: AppSettings) -> User:
    token = request.cookies.get(COOKIE_NAME)
    resolved = await resolve_session(db, token) if token else None
    if resolved is None:
        raise ApiError(401, "unauthenticated", "not logged in")
    user, renewed = resolved
    if renewed:
        set_session_cookie(response, token, settings)
    return user


CurrentUser = Annotated[User, Depends(current_user)]
