from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from vwkanban.auth.deps import AppSettings, CurrentUser, Db
from vwkanban.auth.models import User
from vwkanban.auth.passwords import verify_password
from vwkanban.auth.sessions import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    delete_session,
    set_session_cookie,
)
from vwkanban.auth.users import create_user
from vwkanban.auth.validation import PASSWORD_MAX, check_password, normalize_username
from vwkanban.errors import ApiError

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=PASSWORD_MAX)


class SignupBody(Credentials):
    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return normalize_username(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password(v)


class UserOut(BaseModel):
    id: str
    username: str


class AuthConfig(BaseModel):
    signup_enabled: bool


def _out(user: User) -> UserOut:
    return UserOut(id=str(user.id), username=user.username)


async def _start_session(
    request: Request, response: Response, db: Db, settings: AppSettings, user: User
) -> None:
    # Drop any session the browser already had (no session fixation, no orphans).
    await delete_session(db, request.cookies.get(COOKIE_NAME))
    token = await create_session(db, user.id)
    await db.commit()
    set_session_cookie(response, token, settings)


@router.get("/config")
async def auth_config(settings: AppSettings) -> AuthConfig:
    return AuthConfig(signup_enabled=settings.allow_signup)


@router.post("/login")
async def login(
    body: Credentials, request: Request, response: Response, db: Db, settings: AppSettings
) -> UserOut:
    name = body.username.strip().lower()
    user = await db.scalar(select(User).where(User.username == name))
    ok, new_hash = await verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None:
        raise ApiError(401, "unauthenticated", "invalid username or password")
    if new_hash:
        user.password_hash = new_hash
    await _start_session(request, response, db, settings, user)
    return _out(user)


@router.post("/signup")
async def signup(
    body: SignupBody, request: Request, response: Response, db: Db, settings: AppSettings
) -> UserOut:
    if not settings.allow_signup:
        raise ApiError(404, "not_found", "not found")
    user = await create_user(db, body.username, body.password)
    if user is None:
        raise ApiError(409, "conflict", "username is taken")
    await _start_session(request, response, db, settings, user)
    return _out(user)


@router.post("/logout", status_code=204)
async def logout(
    user: CurrentUser, request: Request, response: Response, db: Db, settings: AppSettings
) -> None:
    await delete_session(db, request.cookies.get(COOKIE_NAME))
    await db.commit()
    clear_session_cookie(response, settings)
    # M4: also close this session's sockets with 4401.


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return _out(user)
