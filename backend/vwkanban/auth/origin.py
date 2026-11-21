"""CSRF defence: state-changing requests must come from PUBLIC_URL's origin."""

from fastapi import Request

from vwkanban.config import normalize_origin
from vwkanban.errors import ApiError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def origin_allowed(origin: str | None, public_origin: str) -> bool:
    return bool(origin) and normalize_origin(origin) == public_origin


async def check_origin(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    settings = request.app.state.settings
    if not origin_allowed(request.headers.get("origin"), settings.public_origin):
        raise ApiError(403, "forbidden", "bad or missing Origin")
