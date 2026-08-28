"""Generic async repository integration tests."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.system_info import SystemInfo
from app.repositories.base import BaseRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_base_repository_crud(migrated_database_url: str) -> None:
    """Exercise transaction-neutral CRUD against the migrated PostgreSQL schema."""

    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            repository = BaseRepository[SystemInfo, int](SystemInfo, session)
            key = f"repository-test-{uuid4().hex}"

            created = await repository.create(SystemInfo(key=key, value="created"))
            assert created.id > 0
            assert created.created_at is not None
            assert created.updated_at is not None

            fetched = await repository.get(created.id)
            assert fetched is created

            records = await repository.list(offset=0, limit=10)
            assert [record.id for record in records] == [created.id]

            updated = await repository.update(created.id, {"value": "updated"})
            assert updated is created
            assert updated.value == "updated"

            assert await repository.delete(created.id) is True
            assert await repository.get(created.id) is None
            assert await repository.delete(created.id) is False

            await session.rollback()
    finally:
        await engine.dispose()
