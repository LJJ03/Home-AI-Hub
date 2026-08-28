"""PostgreSQL connectivity and readiness integration tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.main import create_app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgresql_17_connection(migrated_database_url: str) -> None:
    """Verify asyncpg connectivity and the required PostgreSQL major version."""

    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            raw_version = await connection.scalar(text("SHOW server_version_num"))
    finally:
        await engine.dispose()

    assert raw_version is not None
    assert int(raw_version) // 10_000 == 17


@pytest.mark.integration
def test_ready_with_postgresql(migrated_database_url: str) -> None:
    """Verify readiness through the real FastAPI and database lifecycle."""

    settings = Settings(database_url=migrated_database_url)
    application = create_app(settings)

    with TestClient(application) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
