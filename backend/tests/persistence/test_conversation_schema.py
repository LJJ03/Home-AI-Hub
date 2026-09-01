"""Offline contracts for the conversation persistence metadata."""

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy import inspect as sqlalchemy_inspect

from app.db.base import Base
from app.models import ConversationModel, ConversationTurnModel, MessageModel


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODEL_SOURCE = BACKEND_ROOT / "app" / "models" / "conversations.py"


def _names(table: object, constraint_type: type[object]) -> set[str | None]:
    return {
        item.name
        for item in table.constraints  # type: ignore[attr-defined]
        if isinstance(item, constraint_type)
    }


def test_conversation_tables_are_registered_on_shared_metadata() -> None:
    assert {"conversations", "conversation_turns", "messages"}.issubset(
        Base.metadata.tables
    )
    assert ConversationModel.__table__ is Base.metadata.tables["conversations"]
    assert ConversationTurnModel.__table__ is Base.metadata.tables["conversation_turns"]
    assert MessageModel.__table__ is Base.metadata.tables["messages"]


def test_conversation_schema_columns_and_indexes() -> None:
    table = ConversationModel.__table__

    assert set(table.c.keys()) == {
        "id",
        "title",
        "status",
        "next_sequence",
        "created_at",
        "updated_at",
        "archived_at",
    }
    assert table.c.id.primary_key
    assert table.c.title.type.length == 200
    assert table.c.title.nullable
    assert not table.c.status.nullable
    assert not table.c.next_sequence.nullable
    assert table.c.created_at.type.timezone
    assert table.c.updated_at.type.timezone
    assert table.c.archived_at.type.timezone
    assert table.c.archived_at.nullable
    assert _names(table, CheckConstraint) == {
        "ck_conversations_archived_at_matches_status",
        "ck_conversations_next_sequence_positive",
        "ck_conversations_status_valid",
    }
    assert {index.name for index in table.indexes} == {
        "ix_conversations_status_updated_at",
        "ix_conversations_updated_at",
    }


def test_turn_schema_constraints_and_request_identity_semantics() -> None:
    table = ConversationTurnModel.__table__

    assert set(table.c.keys()) == {
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
    assert table.c.request_id.nullable
    assert table.c.idempotency_key.nullable
    assert _names(table, UniqueConstraint) == {
        "uq_conversation_turns_conversation_id_idempotency_key",
        "uq_conversation_turns_conversation_id_sequence",
    }
    assert not table.c.request_id.unique
    assert not table.c.idempotency_key.unique
    assert table.c.completed_at.type.timezone
    assert table.c.completed_at.nullable
    assert _names(table, CheckConstraint) == {
        "ck_conversation_turns_completion_tokens_nonnegative",
        "ck_conversation_turns_prompt_tokens_nonnegative",
        "ck_conversation_turns_sequence_positive",
        "ck_conversation_turns_status_valid",
        "ck_conversation_turns_total_tokens_nonnegative",
    }

    foreign_keys = list(table.foreign_key_constraints)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].name == (
        "fk_conversation_turns_conversation_id_conversations"
    )
    assert foreign_keys[0].ondelete == "RESTRICT"


def test_message_schema_constraints_indexes_and_delete_policy() -> None:
    table = MessageModel.__table__

    assert set(table.c.keys()) == {
        "id",
        "conversation_id",
        "turn_id",
        "role",
        "content",
        "sequence",
        "created_at",
    }
    assert not table.c.content.nullable
    assert table.c.created_at.type.timezone
    assert _names(table, UniqueConstraint) == {
        "uq_messages_conversation_id_sequence",
        "uq_messages_turn_id_role",
    }
    assert _names(table, CheckConstraint) == {
        "ck_messages_content_not_blank",
        "ck_messages_role_valid",
        "ck_messages_sequence_positive",
    }
    assert {index.name for index in table.indexes} == {
        "ix_messages_conversation_id_sequence"
    }
    foreign_keys = {
        constraint.name: constraint.ondelete
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys == {
        "fk_messages_conversation_id_conversations": "RESTRICT",
        "fk_messages_turn_id_conversation_turns": "RESTRICT",
    }


def test_models_do_not_define_implicit_relationship_cascades() -> None:
    for model in (ConversationModel, ConversationTurnModel, MessageModel):
        assert not list(sqlalchemy_inspect(model).relationships)


def test_schema_excludes_deferred_and_sensitive_payload_fields() -> None:
    forbidden_columns = {
        "authorization",
        "embedding",
        "metadata_json",
        "provider_options",
        "provider_raw_payload",
        "raw_response",
        "stream_chunks",
        "tool_call",
        "user_id",
    }
    actual_columns = {
        column.name
        for model in (ConversationModel, ConversationTurnModel, MessageModel)
        for column in model.__table__.columns
    }
    assert actual_columns.isdisjoint(forbidden_columns)


def test_persistence_models_have_no_runtime_or_infrastructure_side_effects() -> None:
    source = MODEL_SOURCE.read_text(encoding="utf-8").lower()

    forbidden_imports = (
        "fastapi",
        "asyncpg",
        "redis",
        "httpx",
        "app.api",
        "app.llm",
        "app.repositories",
        "app.services",
    )
    forbidden_operations = (
        "create_all",
        "create_async_engine",
        "sessionmaker",
        "os.environ",
        "getenv(",
    )
    for forbidden in (*forbidden_imports, *forbidden_operations):
        assert forbidden not in source
