from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from vwkanban.auth.models import Session, User
from vwkanban.auth.passwords import hash_password
from vwkanban.auth.validation import check_password, normalize_username


async def create_user(db: AsyncSession, username: str, password: str) -> User | None:
    """Validates, hashes and inserts. Returns None if the name is taken (caller commits).
    Raises ValueError for an invalid username or password."""
    name = normalize_username(username)
    password_hash = await hash_password(check_password(password))
    user_id = await db.scalar(
        insert(User)
        .values(username=name, password_hash=password_hash)
        .on_conflict_do_nothing(index_elements=[User.username])
        .returning(User.id)
    )
    return None if user_id is None else await db.get_one(User, user_id)


async def find_user(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == username.strip().lower()))


async def set_password(db: AsyncSession, user: User, password: str) -> None:
    """Changes the password and logs the user out everywhere (caller commits)."""
    user.password_hash = await hash_password(check_password(password))
    await db.execute(delete(Session).where(Session.user_id == user.id))
