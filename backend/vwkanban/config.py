from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
