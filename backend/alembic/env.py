"""Asynchronous Alembic migration environment."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.models  # noqa: F401 - import all models before reading metadata
from app.core.config import get_settings
from app.db.base import Base


config = context.config
settings = get_settings()
target_metadata = Base.metadata


def get_database_url() -> str:
    """Return an explicitly injected URL or the validated runtime setting."""

    override = config.attributes.get("database_url")
    if override is not None:
        if not isinstance(override, str):
            raise TypeError("Alembic database_url override must be a string")
        return override
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Generate PostgreSQL migration SQL without opening a connection."""

    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    """Run migrations through a synchronous facade over an async connection."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a migration-only async engine and release it after use."""

    connectable: AsyncEngine = create_async_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(apply_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run online migrations using the asyncpg-backed engine."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
