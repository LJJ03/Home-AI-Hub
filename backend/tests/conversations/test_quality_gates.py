"""Cross-layer regression gates for the Phase 8 conversation boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.router import api_router
from app.schemas.chat import ChatRequest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
DOMAIN_ROOT = APP_ROOT / "domain/conversations"
APPLICATION_ROOT = APP_ROOT / "application/conversations"
PROVIDER_ROOT = APP_ROOT / "llm/providers"
PERSISTENCE_ROOTS = (
    APP_ROOT / "db",
    APP_ROOT / "models",
    APP_ROOT / "repositories",
)
CONVERSATION_HTTP_PATHS = (
    APP_ROOT / "api/v1/routes/conversations.py",
    APP_ROOT / "api/dependencies/conversations.py",
    APP_ROOT / "api/error_mapping/conversations.py",
    APP_ROOT / "schemas/conversations.py",
)
STATELESS_CHAT_PATHS = (
    APP_ROOT / "api/v1/routes/chat.py",
    APP_ROOT / "api/dependencies/chat.py",
    APP_ROOT / "api/error_mapping/llm.py",
    APP_ROOT / "schemas/chat.py",
    APP_ROOT / "services/chat.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _python_files(*roots: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for root in roots
        for path in sorted(root.rglob("*.py"))
    )


def _assert_imports_exclude(
    paths: tuple[Path, ...],
    forbidden_prefixes: tuple[str, ...],
) -> None:
    for path in paths:
        forbidden = {
            module
            for module in _imports(path)
            if module.startswith(forbidden_prefixes)
        }
        assert not forbidden, f"{path} imports forbidden modules: {sorted(forbidden)}"


def test_phase8_dependency_direction_is_enforced_across_every_layer() -> None:
    _assert_imports_exclude(
        _python_files(DOMAIN_ROOT),
        (
            "fastapi",
            "pydantic",
            "sqlalchemy",
            "asyncpg",
            "redis",
            "httpx",
            "app.api",
            "app.application",
            "app.db",
            "app.llm",
            "app.models",
            "app.repositories",
            "app.services",
        ),
    )
    _assert_imports_exclude(
        _python_files(APPLICATION_ROOT),
        (
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
            "app.llm.registry",
            "app.llm.factory",
            "app.llm.bootstrap",
        ),
    )
    _assert_imports_exclude(
        _python_files(*PERSISTENCE_ROOTS),
        (
            "fastapi",
            "app.api",
            "app.application",
            "app.llm",
            "app.services",
        ),
    )
    _assert_imports_exclude(
        tuple(sorted(PROVIDER_ROOT.glob("*.py"))),
        (
            "app.api",
            "app.application.conversations",
            "app.domain.conversations",
            "app.models",
            "app.repositories",
            "app.schemas.conversations",
        ),
    )


def test_conversation_http_adapter_keeps_provider_and_transport_details_private() -> None:
    _assert_imports_exclude(
        CONVERSATION_HTTP_PATHS,
        (
            "asyncpg",
            "redis",
            "httpx",
            "app.llm.bootstrap",
            "app.llm.config",
            "app.llm.factory",
            "app.llm.providers",
            "app.llm.registry",
        ),
    )
    combined_source = "\n".join(
        path.read_text(encoding="utf-8") for path in CONVERSATION_HTTP_PATHS
    ).lower()

    for forbidden_fragment in (
        "authorization_header",
        "provider_request_id",
        "raw_json",
        "raw_response",
        "stream_generate",
        "websocket",
    ):
        assert forbidden_fragment not in combined_source


def test_phase5_chat_request_remains_stateless_and_rejects_conversation_id() -> None:
    assert "conversation_id" not in ChatRequest.model_fields
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "messages": [{"role": "user", "content": "offline request"}],
                "conversation_id": "11111111-1111-4111-8111-111111111111",
            }
        )

    _assert_imports_exclude(
        STATELESS_CHAT_PATHS,
        (
            "app.api.dependencies.conversations",
            "app.application.conversations",
            "app.domain.conversations",
            "app.models.conversations",
            "app.repositories.conversations",
            "app.repositories.unit_of_work",
            "app.schemas.conversations",
        ),
    )


def test_public_route_surface_contains_only_the_frozen_and_phase8_endpoints() -> None:
    application = FastAPI()
    application.include_router(api_router)
    actual_routes = {
        (path, method.upper())
        for path, path_item in application.openapi()["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert actual_routes == {
        ("/health", "GET"),
        ("/ready", "GET"),
        ("/version", "GET"),
        ("/api/v1/chat/completions", "POST"),
        ("/api/v1/conversations", "GET"),
        ("/api/v1/conversations", "POST"),
        ("/api/v1/conversations/{conversation_id}", "GET"),
        ("/api/v1/conversations/{conversation_id}/messages", "GET"),
        ("/api/v1/conversations/{conversation_id}/turns", "POST"),
        ("/api/v1/conversations/{conversation_id}/archive", "POST"),
    }


def test_application_sources_never_create_schema_or_log_conversation_content() -> None:
    phase8_paths = _python_files(DOMAIN_ROOT, APPLICATION_ROOT) + CONVERSATION_HTTP_PATHS
    source = "\n".join(path.read_text(encoding="utf-8") for path in phase8_paths)

    assert "create_all" not in source
    assert "logging" not in {
        module for path in phase8_paths for module in _imports(path)
    }
    assert "OPENAI_API_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source
