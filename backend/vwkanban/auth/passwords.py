"""argon2id hashing. Hashing is CPU- and memory-heavy, so it runs in a thread pool
and at most `_MAX_CONCURRENT` hashes run at once (the app container has 256 MB)."""

import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# OWASP baseline for argon2id: m=19 MiB, t=2, p=1.
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1, type=Type.ID)
_MAX_CONCURRENT = 2
_limiter: anyio.CapacityLimiter | None = None
# Verified when the username doesn't exist, so timing doesn't reveal which names exist.
_DUMMY_HASH = _hasher.hash("vwkanban-dummy-password")


def _get_limiter() -> anyio.CapacityLimiter:
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(_MAX_CONCURRENT)
    return _limiter


def hash_password_sync(password: str) -> str:
    return _hasher.hash(password)


def verify_password_sync(stored: str | None, password: str) -> tuple[bool, str | None]:
    """Returns (ok, new_hash). new_hash is set when the stored hash uses old parameters."""
    try:
        _hasher.verify(stored or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False, None
    if stored is None:
        return False, None
    return True, (_hasher.hash(password) if _hasher.check_needs_rehash(stored) else None)


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(hash_password_sync, password, limiter=_get_limiter())


async def verify_password(stored: str | None, password: str) -> tuple[bool, str | None]:
    return await anyio.to_thread.run_sync(
        verify_password_sync, stored, password, limiter=_get_limiter()
    )
