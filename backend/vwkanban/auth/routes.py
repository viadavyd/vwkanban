from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from vwkanban.auth.deps import AppSettings, CurrentUser, Db
from vwkanban.auth.models import User
from vwkanban.auth.passwords import verify_password
from vwkanban.auth.sessions import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    delete_session,
    hash_token,
    set_session_cookie,
)
from vwkanban.auth.users import create_user
from vwkanban.auth.validation import PASSWORD_MAX, check_password, normalize_username
from vwkanban.errors import ApiError
from vwkanban.sync.ws import CLOSE_NO_SESSION

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
async def signup(request: Request, response: Response, db: Db, settings: AppSettings) -> UserOut:
    # The flag is checked before the body is parsed, so signup looks absent (404) for any
    # request while it is off. A typed body param would be validated first (422).
    if not settings.allow_signup:
        raise ApiError(404, "not_found", "not found")
    try:
        body = SignupBody.model_validate_json(await request.body())
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from None
    user = await create_user(db, body.username, body.password)
    if user is None:
        raise ApiError(409, "conflict", "username is taken")
    await _start_session(request, response, db, settings, user)
    return _out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: Db, settings: AppSettings) -> None:
    # No session required: an expired or unknown cookie is still cleared (idempotent).
    token = request.cookies.get(COOKIE_NAME)
    await delete_session(db, token)
    await db.commit()
    clear_session_cookie(response, settings)
    if token:
        request.app.state.hub.close_session(hash_token(token), CLOSE_NO_SESSION)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return _out(user)
