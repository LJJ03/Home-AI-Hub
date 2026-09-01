"""Static Phase 8 Conversation API boundary contracts."""

from __future__ import annotations

import ast
from pathlib import Path

from app.schemas.conversations import CreateConversationRequest, CreateTurnRequest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ROUTER_PATH = BACKEND_ROOT / "app/api/v1/routes/conversations.py"
SCHEMA_PATH = BACKEND_ROOT / "app/schemas/conversations.py"
DEPENDENCY_PATH = BACKEND_ROOT / "app/api/dependencies/conversations.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_router_only_uses_http_and_application_boundaries() -> None:
    imports = _imports(ROUTER_PATH)
    forbidden = (
        "sqlalchemy",
        "asyncpg",
        "redis",
        "httpx",
        "app.db",
        "app.models",
        "app.repositories",
        "app.llm",
    )

    assert all(not module.startswith(forbidden) for module in imports)


def test_schema_has_no_orm_or_infrastructure_dependency() -> None:
    imports = _imports(SCHEMA_PATH)
    forbidden = (
        "sqlalchemy",
        "asyncpg",
        "redis",
        "httpx",
        "app.db",
        "app.models",
        "app.repositories",
        "app.llm",
    )

    assert all(not module.startswith(forbidden) for module in imports)


def test_dependency_wiring_has_no_provider_or_configuration_access() -> None:
    imports = _imports(DEPENDENCY_PATH)
    forbidden = (
        "app.llm.providers",
        "app.llm.registry",
        "app.llm.factory",
        "app.llm.bootstrap",
        "app.llm.config",
        "pydantic_settings",
        "os",
        "asyncpg",
        "redis",
        "httpx",
    )

    assert all(not module.startswith(forbidden) for module in imports)


def test_turn_schema_forbids_stream_provider_model_system_and_tools() -> None:
    fields = set(CreateTurnRequest.model_fields)

    assert fields == {"content", "idempotency_key"}
    assert "stream" not in fields
    assert "provider_name" not in fields
    assert "model_name" not in fields
    assert "system" not in fields
    assert "tools" not in fields
    assert "user_id" not in set(CreateConversationRequest.model_fields)
