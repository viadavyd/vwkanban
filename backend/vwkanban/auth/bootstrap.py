import logging

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vwkanban.auth.models import User
from vwkanban.auth.users import create_user
from vwkanban.config import Settings

log = logging.getLogger("vwkanban.auth")


async def ensure_admin(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> bool:
    """Creates ADMIN_USERNAME on first start (users table empty). Returns True if created."""
    if not (settings.admin_username and settings.admin_password):
        return False
    async with sessionmaker() as db:
        if await db.scalar(select(exists().select_from(User))):
            return False
        try:
            user = await create_user(db, settings.admin_username, settings.admin_password)
        except ValueError as e:
            log.error("ADMIN_USERNAME/ADMIN_PASSWORD rejected, no admin created: %s", e)
            return False
        await db.commit()
    if user is not None:
        log.warning("created admin user %r from .env", user.username)
    return user is not None
