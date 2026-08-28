"""FastAPI adapters for database manager and session injection."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DatabaseManager


def get_database_manager(request: Request) -> DatabaseManager:
    """Return the manager initialized by the application lifespan."""

    manager = getattr(request.app.state, "database_manager", None)
    if not isinstance(manager, DatabaseManager):
        raise RuntimeError("Database manager is not initialized")
    return manager


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session without committing automatically."""

    manager = get_database_manager(request)
    async with manager.session() as session:
        yield session

