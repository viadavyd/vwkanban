from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_PORTS = {"http": 80, "https": 443}


class Settings(BaseSettings):
    """App settings, read from the environment (compose passes `.env`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_url: str = "http://localhost"
    postgres_user: str = "vwkanban"
    postgres_password: str = ""
    postgres_db: str = "vwkanban"
    postgres_host: str = "db"
    postgres_port: int = 5432
    # Full URL override, e.g. for tests and local dev.
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    allow_signup: bool = False
    # First admin, created on start when the users table is empty.
    admin_username: str | None = None
    admin_password: str | None = None
    # Override only; by default the cookie's Secure flag follows PUBLIC_URL's scheme.
    cookie_secure: bool | None = None

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return urlsplit(self.public_url).scheme.lower() == "https"

    @property
    def public_origin(self) -> str:
        return normalize_origin(self.public_url)


def normalize_origin(url: str) -> str:
    """`scheme://host[:port]`, lowercased, default port dropped. '' if unparseable."""
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""
    if not scheme or not host:
        return ""
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
