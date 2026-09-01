"""Static boundaries for the Phase 8 conversation application layer."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_ROOT = BACKEND_ROOT / "app" / "application" / "conversations"

FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "asyncpg",
    "redis",
    "httpx",
    "app.api",
    "app.db",
    "app.models",
    "app.repositories",
    "app.llm.providers",
    "app.llm.bootstrap",
    "app.llm.factory",
    "app.llm.registry",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return tuple(modules)


def test_conversation_application_layer_has_no_forbidden_dependencies() -> None:
    for path in APPLICATION_ROOT.glob("*.py"):
        for module in _imports(path):
            assert not module.startswith(FORBIDDEN_IMPORT_PREFIXES), (
                f"{path.name} must not import {module}"
            )


def test_chat_service_has_no_streaming_retry_fallback_or_provider_logic() -> None:
    source = (APPLICATION_ROOT / "services.py").read_text(encoding="utf-8")
    lowered = source.lower()

    assert "stream_generate" not in source
    assert "asyncclient" not in lowered
    assert "authorization" not in lowered
    assert "retry" not in lowered
    assert "fallback" not in lowered
    assert "deepseek" not in lowered
    assert "openai" not in lowered
    assert "provider_request_id" not in source


def test_application_layer_does_not_create_api_or_persistence_artifacts() -> None:
    names = {path.name for path in APPLICATION_ROOT.glob("*.py")}

    assert "router.py" not in names
    assert "models.py" not in names
    assert "migration.py" not in names
