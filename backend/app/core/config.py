"""Typed application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    """Validated runtime settings shared by the application."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    name: str = "Home AI Hub API"
    version: str = __version__
    environment: Literal["local", "test", "production"] = "local"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    sqlalchemy_echo: bool = Field(validation_alias="SQLALCHEMY_ECHO")
    pool_size: int = Field(ge=1, le=100, validation_alias="POOL_SIZE")
    max_overflow: int = Field(ge=0, le=100, validation_alias="MAX_OVERFLOW")
    database_healthcheck_timeout_seconds: float = Field(
        gt=0,
        le=30,
        validation_alias="DATABASE_HEALTHCHECK_TIMEOUT_SECONDS",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Require the asynchronous PostgreSQL driver in the database URL."""

        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg scheme")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
