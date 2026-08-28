"""Alembic migration integration tests."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def _read_schema(
    connection: Connection,
) -> tuple[set[str], str | None, set[str | None]]:
    """Read the migrated table and constraint names synchronously."""

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    primary_key_name = inspector.get_pk_constraint("system_info").get("name")
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("system_info")
    }
    return tables, primary_key_name, unique_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_upgrade_reaches_head(
    migrated_database_url: str,
    alembic_head_revision: str,
) -> None:
    """Verify that migrations create the expected versioned PostgreSQL schema."""

    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            tables, primary_key_name, unique_names = await connection.run_sync(
                _read_schema
            )
    finally:
        await engine.dispose()

    assert revision == alembic_head_revision
    assert {"alembic_version", "system_info"}.issubset(tables)
    assert primary_key_name == "pk_system_info"
    assert "uq_system_info_key" in unique_names
