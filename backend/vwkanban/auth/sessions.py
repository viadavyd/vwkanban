"""Server-side sessions. The cookie holds a random token; the DB stores its sha256."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.auth.models import Session, User
from vwkanban.config import Settings

COOKIE_NAME = "vwk_session"
SESSION_TTL = timedelta(days=30)
# Sliding expiry: extend at most once per this interval (avoids a write per request).
RENEW_EVERY = timedelta(days=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def create_session(db: AsyncSession, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(id=hash_token(token), user_id=user_id, expires_at=_now() + SESSION_TTL))
    return token


async def delete_session(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(Session).where(Session.id == hash_token(token)))


async def resolve_session(db: AsyncSession, token: str) -> tuple[User, bool] | None:
    """Returns (user, renewed) for a live session; deletes it if expired."""
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.id == hash_token(token))
        )
    ).first()
    if row is None:
        return None
    session, user = row
    now = _now()
    if session.expires_at <= now:
        await db.execute(delete(Session).where(Session.id == session.id))
        await db.commit()
        return None
    renewed = False
    if session.expires_at < now + SESSION_TTL - RENEW_EVERY:
        await db.execute(
            update(Session).where(Session.id == session.id).values(expires_at=now + SESSION_TTL)
        )
        await db.commit()
        renewed = True
    return user, renewed


async def purge_expired(db: AsyncSession) -> None:
    await db.execute(delete(Session).where(Session.expires_at <= func.now()))
    await db.commit()


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.secure_cookies
    )
