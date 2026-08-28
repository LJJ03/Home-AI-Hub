"""Asynchronous SQLAlchemy engine and session lifecycle management."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class DatabaseUnavailableError(RuntimeError):
    """Report a failed database connectivity check without leaking driver details."""


class DatabaseManager:
    """Own the process-wide async engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_started(self) -> bool:
        """Return whether the engine and session factory are initialized."""

        return self._engine is not None and self._session_factory is not None

    @property
    def engine(self) -> AsyncEngine:
        """Return the initialized engine or fail on lifecycle misuse."""

        if self._engine is None:
            raise RuntimeError("Database manager has not been started")
        return self._engine

    def start(self) -> None:
        """Initialize the lazy async engine and session factory once."""

        if self.is_started:
            return

        engine = create_async_engine(
            self._settings.database_url.get_secret_value(),
            echo=self._settings.sqlalchemy_echo,
            pool_size=self._settings.pool_size,
            max_overflow=self._settings.max_overflow,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )

        self._engine = engine
        self._session_factory = session_factory

    async def check_connection(self) -> None:
        """Execute a bounded lightweight query against the configured database."""

        try:
            async with asyncio.timeout(
                self._settings.database_healthcheck_timeout_seconds
            ):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            raise DatabaseUnavailableError(
                "Database connectivity check failed"
            ) from exc

    async def stop(self) -> None:
        """Dispose the engine and make future sessions unavailable."""

        engine = self._engine
        self._session_factory = None
        self._engine = None
        if engine is not None:
            await engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session without owning the caller's commit boundary."""

        session_factory = self._session_factory
        if session_factory is None:
            raise RuntimeError("Database manager has not been started")

        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
