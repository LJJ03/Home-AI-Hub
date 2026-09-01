"""Offline Alembic graph and migration-content contracts."""

import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
VERSIONS_ROOT = ALEMBIC_ROOT / "versions"
BASELINE_MIGRATION = VERSIONS_ROOT / "20260826_0001_create_system_info.py"
CONVERSATION_MIGRATION = (
    VERSIONS_ROOT / "20260901_0002_create_conversation_schema.py"
)


def _assignment_value(tree: ast.Module, variable: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == variable:
                return ast.literal_eval(node.value)
    raise AssertionError(f"Missing migration assignment: {variable}")


def test_alembic_has_one_conversation_head_after_phase_7_baseline() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ALEMBIC_ROOT))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260901_0002"]
    revision = scripts.get_revision("20260901_0002")
    assert revision is not None
    assert revision.down_revision == "20260826_0001"


def test_migration_revision_chain_and_downgrade_are_explicit() -> None:
    baseline_source = BASELINE_MIGRATION.read_text(encoding="utf-8")
    migration_source = CONVERSATION_MIGRATION.read_text(encoding="utf-8")
    baseline_tree = ast.parse(baseline_source)
    migration_tree = ast.parse(migration_source)

    assert _assignment_value(baseline_tree, "revision") == "20260826_0001"
    assert _assignment_value(baseline_tree, "down_revision") is None
    assert _assignment_value(migration_tree, "revision") == "20260901_0002"
    assert _assignment_value(migration_tree, "down_revision") == "20260826_0001"
    function_names = {
        node.name for node in migration_tree.body if isinstance(node, ast.FunctionDef)
    }
    assert {"upgrade", "downgrade"}.issubset(function_names)
    assert "create_all" not in migration_source


def test_migration_creates_and_drops_tables_in_dependency_order() -> None:
    source = CONVERSATION_MIGRATION.read_text(encoding="utf-8")

    create_positions = [
        source.index(f'        "{table}",')
        for table in ("conversations", "conversation_turns", "messages")
    ]
    assert create_positions == sorted(create_positions)

    downgrade_source = source[source.index("def downgrade()") :]
    drop_positions = [
        downgrade_source.index(f'op.drop_table("{table}")')
        for table in ("messages", "conversation_turns", "conversations")
    ]
    assert drop_positions == sorted(drop_positions)


def test_migration_has_required_schema_contracts_and_no_deferred_payloads() -> None:
    source = CONVERSATION_MIGRATION.read_text(encoding="utf-8")

    required_names = {
        "ck_conversations_status_valid",
        "ck_conversation_turns_status_valid",
        "ck_messages_role_valid",
        "fk_conversation_turns_conversation_id_conversations",
        "fk_messages_conversation_id_conversations",
        "fk_messages_turn_id_conversation_turns",
        "ix_conversations_status_updated_at",
        "ix_conversations_updated_at",
        "ix_messages_conversation_id_sequence",
        "uq_conversation_turns_conversation_id_idempotency_key",
        "uq_conversation_turns_conversation_id_sequence",
        "uq_messages_conversation_id_sequence",
        "uq_messages_turn_id_role",
    }
    for name in required_names:
        assert name in source
    assert source.count('ondelete="RESTRICT"') == 3

    forbidden = (
        "authorization_header",
        "embedding",
        "provider_options",
        "provider_raw_payload",
        "raw_response",
        "stream_chunks",
        "tool_call",
        '"user_id"',
    )
    for value in forbidden:
        assert value not in source.lower()
