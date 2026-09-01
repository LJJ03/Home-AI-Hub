"""Dependency and storage-boundary gates for the conversation domain."""

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
DOMAIN_ROOT = BACKEND_ROOT / "app/domain/conversations"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_conversation_domain_has_only_domain_and_standard_library_dependencies() -> None:
    forbidden_prefixes = (
        "fastapi",
        "starlette",
        "pydantic",
        "sqlalchemy",
        "asyncpg",
        "redis",
        "httpx",
        "requests",
        "socket",
        "os",
        "logging",
        "app.api",
        "app.db",
        "app.infrastructure",
        "app.llm",
        "app.models",
        "app.persistence",
        "app.repositories",
        "app.services",
    )

    source_paths = sorted(DOMAIN_ROOT.glob("*.py"))

    assert source_paths
    for source_path in source_paths:
        imported = _imported_modules(source_path)
        assert not any(
            module.startswith(forbidden_prefixes) for module in imported
        ), f"{source_path} imports a forbidden module: {sorted(imported)}"


def test_conversation_domain_has_no_infrastructure_or_provider_payload_fields() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOMAIN_ROOT.glob("*.py"))
    ).lower()
    forbidden_fragments = (
        "authorization_header",
        "api_key",
        "raw_json",
        "raw_response",
        "http_request",
        "http_response",
        "provider_request_id",
        "stream_chunks",
        "create_all",
        "getenv",
        "environ",
    )

    assert not any(fragment in source for fragment in forbidden_fragments)


def test_conversation_domain_does_not_define_persistence_or_http_components() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOMAIN_ROOT.glob("*.py"))
    )

    for forbidden_symbol in (
        "APIRouter",
        "AsyncSession",
        "BaseRepository",
        "ConversationRepository",
        "ConversationService",
        "Mapped[",
        "mapped_column",
    ):
        assert forbidden_symbol not in source

