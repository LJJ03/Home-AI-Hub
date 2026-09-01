"""Alembic migration integration tests."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


def _constraint_names(items: list[dict[str, Any]]) -> set[str | None]:
    return {item.get("name") for item in items}


def _read_schema(connection: Connection) -> dict[str, Any]:
    """Read migrated tables, columns, constraints, indexes, and FKs."""

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    return {
        "tables": tables,
        "system_info_pk": inspector.get_pk_constraint("system_info").get("name"),
        "system_info_unique": _constraint_names(
            inspector.get_unique_constraints("system_info")
        ),
        "columns": {
            table: {column["name"]: column for column in inspector.get_columns(table)}
            for table in ("conversations", "conversation_turns", "messages")
        },
        "checks": {
            table: _constraint_names(inspector.get_check_constraints(table))
            for table in ("conversations", "conversation_turns", "messages")
        },
        "uniques": {
            table: _constraint_names(inspector.get_unique_constraints(table))
            for table in ("conversation_turns", "messages")
        },
        "indexes": {
            table: _constraint_names(inspector.get_indexes(table))
            for table in ("conversations", "messages")
        },
        "foreign_keys": {
            table: {
                item["name"]: item.get("options", {}).get("ondelete")
                for item in inspector.get_foreign_keys(table)
            }
            for table in ("conversation_turns", "messages")
        },
    }


async def _expect_integrity_error(
    engine: AsyncEngine,
    statement: str,
    parameters: Mapping[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(statement), parameters)


async def _verify_database_constraints(engine: AsyncEngine) -> None:
    conversation_id = uuid4()
    turn_one_id = uuid4()
    turn_two_id = uuid4()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO conversations (id, status) "
                "VALUES (:id, 'active')"
            ),
            {"id": conversation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO conversation_turns "
                "(id, conversation_id, sequence, request_id, idempotency_key, status) "
                "VALUES (:id, :conversation_id, 1, 'shared-request', 'idem-one', "
                "'pending')"
            ),
            {"id": turn_one_id, "conversation_id": conversation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO conversation_turns "
                "(id, conversation_id, sequence, request_id, idempotency_key, status) "
                "VALUES (:id, :conversation_id, 2, 'shared-request', 'idem-two', "
                "'completed')"
            ),
            {"id": turn_two_id, "conversation_id": conversation_id},
        )
        await connection.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, turn_id, role, content, sequence) "
                "VALUES (:id, :conversation_id, :turn_id, 'user', "
                "'offline migration test', 1)"
            ),
            {
                "id": uuid4(),
                "conversation_id": conversation_id,
                "turn_id": turn_one_id,
            },
        )
        repeated_request_count = await connection.scalar(
            text(
                "SELECT count(*) FROM conversation_turns "
                "WHERE conversation_id = :conversation_id "
                "AND request_id = 'shared-request'"
            ),
            {"conversation_id": conversation_id},
        )
    assert repeated_request_count == 2

    turn_insert = (
        "INSERT INTO conversation_turns "
        "(id, conversation_id, sequence, request_id, idempotency_key, status, "
        "prompt_tokens) VALUES (:id, :conversation_id, :sequence, :request_id, "
        ":idempotency_key, :status, :prompt_tokens)"
    )
    base_turn_parameters: dict[str, object] = {
        "conversation_id": conversation_id,
        "request_id": "another-request",
        "status": "pending",
        "prompt_tokens": 0,
    }
    await _expect_integrity_error(
        engine,
        turn_insert,
        {
            **base_turn_parameters,
            "id": uuid4(),
            "sequence": 1,
            "idempotency_key": "unique-key",
        },
    )
    await _expect_integrity_error(
        engine,
        turn_insert,
        {
            **base_turn_parameters,
            "id": uuid4(),
            "sequence": 3,
            "idempotency_key": "idem-one",
        },
    )
    await _expect_integrity_error(
        engine,
        turn_insert,
        {
            **base_turn_parameters,
            "id": uuid4(),
            "sequence": 3,
            "idempotency_key": "invalid-status",
            "status": "unknown",
        },
    )
    await _expect_integrity_error(
        engine,
        turn_insert,
        {
            **base_turn_parameters,
            "id": uuid4(),
            "sequence": 3,
            "idempotency_key": "negative-token",
            "prompt_tokens": -1,
        },
    )

    message_insert = (
        "INSERT INTO messages "
        "(id, conversation_id, turn_id, role, content, sequence) "
        "VALUES (:id, :conversation_id, :turn_id, :role, :content, :sequence)"
    )
    await _expect_integrity_error(
        engine,
        message_insert,
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "turn_id": turn_two_id,
            "role": "user",
            "content": "duplicate sequence",
            "sequence": 1,
        },
    )
    await _expect_integrity_error(
        engine,
        message_insert,
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "turn_id": turn_one_id,
            "role": "user",
            "content": "duplicate turn role",
            "sequence": 2,
        },
    )
    await _expect_integrity_error(
        engine,
        message_insert,
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "turn_id": turn_two_id,
            "role": "system",
            "content": "invalid role",
            "sequence": 2,
        },
    )
    await _expect_integrity_error(
        engine,
        message_insert,
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "turn_id": turn_two_id,
            "role": "assistant",
            "content": "   ",
            "sequence": 2,
        },
    )
    await _expect_integrity_error(
        engine,
        "DELETE FROM conversations WHERE id = :id",
        {"id": conversation_id},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_upgrade_reaches_head(
    migrated_database_url: str,
    alembic_head_revision: str,
) -> None:
    """Verify the Phase 7-to-head upgrade and conversation DB constraints."""

    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            schema = await connection.run_sync(_read_schema)

        assert revision == alembic_head_revision == "20260901_0002"
        assert {
            "alembic_version",
            "system_info",
            "conversations",
            "conversation_turns",
            "messages",
        }.issubset(schema["tables"])
        assert schema["system_info_pk"] == "pk_system_info"
        assert "uq_system_info_key" in schema["system_info_unique"]

        columns = schema["columns"]
        assert set(columns["conversations"]) == {
            "id",
            "title",
            "status",
            "next_sequence",
            "created_at",
            "updated_at",
            "archived_at",
        }
        assert set(columns["messages"]) == {
            "id",
            "conversation_id",
            "turn_id",
            "role",
            "content",
            "sequence",
            "created_at",
        }
        assert set(columns["conversation_turns"]) == {
            "id",
            "conversation_id",
            "sequence",
            "request_id",
            "idempotency_key",
            "status",
            "provider_name",
            "model_name",
            "finish_reason",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "safe_error_code",
            "created_at",
            "updated_at",
            "completed_at",
        }
        assert columns["conversations"]["created_at"]["type"].timezone
        assert columns["conversations"]["updated_at"]["type"].timezone
        assert columns["conversation_turns"]["completed_at"]["type"].timezone
        assert columns["messages"]["created_at"]["type"].timezone

        assert {
            "ck_conversations_archived_at_matches_status",
            "ck_conversations_next_sequence_positive",
            "ck_conversations_status_valid",
        } == schema["checks"]["conversations"]
        assert {
            "ck_conversation_turns_completion_tokens_nonnegative",
            "ck_conversation_turns_prompt_tokens_nonnegative",
            "ck_conversation_turns_sequence_positive",
            "ck_conversation_turns_status_valid",
            "ck_conversation_turns_total_tokens_nonnegative",
        } == schema["checks"]["conversation_turns"]
        assert {
            "ck_messages_content_not_blank",
            "ck_messages_role_valid",
            "ck_messages_sequence_positive",
        } == schema["checks"]["messages"]

        assert {
            "uq_conversation_turns_conversation_id_idempotency_key",
            "uq_conversation_turns_conversation_id_sequence",
        } == schema["uniques"]["conversation_turns"]
        assert {
            "uq_messages_conversation_id_sequence",
            "uq_messages_turn_id_role",
        } == schema["uniques"]["messages"]
        assert {
            "ix_conversations_status_updated_at",
            "ix_conversations_updated_at",
        }.issubset(schema["indexes"]["conversations"])
        assert "ix_messages_conversation_id_sequence" in schema["indexes"][
            "messages"
        ]
        assert schema["foreign_keys"] == {
            "conversation_turns": {
                "fk_conversation_turns_conversation_id_conversations": "RESTRICT"
            },
            "messages": {
                "fk_messages_conversation_id_conversations": "RESTRICT",
                "fk_messages_turn_id_conversation_turns": "RESTRICT",
            },
        }

        await _verify_database_constraints(engine)
    finally:
        await engine.dispose()
