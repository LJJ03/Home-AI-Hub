"""Cross-phase architecture and offline quality gates for the Chat API."""

import ast
import re
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.api.router import api_router
from app.llm.bootstrap import bootstrap_llm
from app.llm.config import LLMSettings


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
TESTS_ROOT = BACKEND_ROOT / "tests"
CHAT_SCHEMA_PATH = APP_ROOT / "schemas/chat.py"
CHAT_SERVICE_PATH = APP_ROOT / "services/chat.py"
CHAT_ROUTE_PATH = APP_ROOT / "api/v1/routes/chat.py"
CHAT_DEPENDENCY_PATH = APP_ROOT / "api/dependencies/chat.py"
LLM_ERROR_MAPPING_PATH = APP_ROOT / "api/error_mapping/llm.py"
FACTORY_PATH = APP_ROOT / "llm/factory.py"
LLM_SERVICE_PATH = APP_ROOT / "llm/service.py"
LLM_PUBLIC_INIT_PATH = APP_ROOT / "llm/__init__.py"
LLM_HTTP_ROOT = APP_ROOT / "llm/http"
LLM_SCHEMA_ROOT = APP_ROOT / "llm/schemas"
PROVIDERS_ROOT = APP_ROOT / "llm/providers"
SYSTEM_ROUTE_PATH = APP_ROOT / "api/routes/system.py"
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
CONFTEST_PATH = TESTS_ROOT / "conftest.py"
LLM_INTEGRATION_ROOT = TESTS_ROOT / "integration/llm"
PERSISTENCE_ROOTS = (
    APP_ROOT / "db",
    APP_ROOT / "models",
    APP_ROOT / "repositories",
)
POSTGRESQL_TEST_PATHS = (
    TESTS_ROOT / "test_database.py",
    TESTS_ROOT / "test_migrations.py",
    TESTS_ROOT / "test_repository.py",
)


def _syntax_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(path: Path) -> set[str]:
    imported_modules: set[str] = set()
    for node in ast.walk(_syntax_tree(path)):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
    return imported_modules


def _assert_no_forbidden_imports(
    path: Path,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    imported_modules = _imported_modules(path)
    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    ), f"{path} imports a forbidden module: {sorted(imported_modules)}"


def test_all_application_and_test_sources_are_syntax_valid() -> None:
    source_paths = sorted(APP_ROOT.rglob("*.py")) + sorted(TESTS_ROOT.rglob("*.py"))

    assert source_paths
    for source_path in source_paths:
        _syntax_tree(source_path)


@pytest.mark.parametrize(
    ("source_path", "forbidden_prefixes"),
    (
        (
            CHAT_SCHEMA_PATH,
            (
                "fastapi",
                "starlette",
                "app.api",
                "app.llm",
                "app.db",
                "app.models",
                "app.repositories",
                "sqlalchemy",
                "redis",
            ),
        ),
        (
            CHAT_SERVICE_PATH,
            (
                "fastapi",
                "starlette",
                "app.api",
                "app.db",
                "app.models",
                "app.repositories",
                "sqlalchemy",
                "redis",
                "app.llm.providers",
                "app.llm.registry",
                "app.llm.factory",
                "app.llm.bootstrap",
                "pydantic_settings",
            ),
        ),
        (
            CHAT_ROUTE_PATH,
            (
                "app.db",
                "app.models",
                "app.repositories",
                "sqlalchemy",
                "redis",
                "app.llm.service",
                "app.llm.providers",
                "app.llm.registry",
                "app.llm.factory",
                "app.llm.bootstrap",
                "app.core.config",
                "pydantic_settings",
            ),
        ),
        (
            CHAT_DEPENDENCY_PATH,
            (
                "app.db",
                "app.models",
                "app.repositories",
                "sqlalchemy",
                "redis",
                "app.llm.providers",
                "app.llm.registry",
                "app.llm.factory",
                "app.llm.bootstrap",
                "app.llm.config",
                "app.core.config",
                "pydantic_settings",
            ),
        ),
        (
            LLM_ERROR_MAPPING_PATH,
            (
                "app.db",
                "app.models",
                "app.repositories",
                "sqlalchemy",
                "redis",
                "app.llm.service",
                "app.llm.providers",
                "app.llm.registry",
                "app.llm.factory",
                "app.llm.bootstrap",
            ),
        ),
    ),
    ids=("schema", "service", "route", "dependency", "error-mapping"),
)
def test_chat_layer_dependency_direction_is_enforced(
    source_path: Path,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    common_forbidden = (
        "httpx",
        "requests",
        "aiohttp",
        "socket",
        "websockets",
    )
    _assert_no_forbidden_imports(
        source_path,
        forbidden_prefixes + common_forbidden,
    )


def test_chat_route_uses_only_chat_service_dependency() -> None:
    syntax_tree = _syntax_tree(CHAT_ROUTE_PATH)
    dependency_targets = {
        ast.unparse(node.args[0])
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Depends"
        and node.args
    }
    imported_modules = _imported_modules(CHAT_ROUTE_PATH)

    assert dependency_targets == {"get_chat_service"}
    assert "app.api.dependencies.chat" in imported_modules
    assert not any(
        module.startswith(
            ("app.api.dependencies.database", "app.db", "sqlalchemy")
        )
        for module in imported_modules
    )


def test_chat_api_sources_remain_stateless_and_transport_limited() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            CHAT_SCHEMA_PATH,
            CHAT_SERVICE_PATH,
            CHAT_ROUTE_PATH,
            CHAT_DEPENDENCY_PATH,
        )
    )

    for forbidden_symbol in (
        "conversation_id",
        "ChatRepository",
        "MessageRepository",
        "UserRepository",
        "WebSocket",
    ):
        assert forbidden_symbol not in source_text


def test_provider_sdks_are_absent_and_adapter_set_is_explicit() -> None:
    forbidden_import_prefixes = (
        "openai",
        "anthropic",
        "deepseek",
        "google.generativeai",
        "google.genai",
        "dashscope",
        "langchain",
        "llama_index",
    )
    for source_path in APP_ROOT.rglob("*.py"):
        _assert_no_forbidden_imports(source_path, forbidden_import_prefixes)

    manifest = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dependency_values = list(manifest["project"].get("dependencies", ()))
    for optional_group in manifest["project"].get(
        "optional-dependencies", {}
    ).values():
        dependency_values.extend(optional_group)
    installed_names = {
        re.split(r"[<>=!~;\[]", dependency, maxsplit=1)[0]
        .strip()
        .lower()
        .replace("_", "-")
        for dependency in dependency_values
    }
    forbidden_distributions = {
        "openai",
        "anthropic",
        "deepseek",
        "google-generativeai",
        "google-genai",
        "dashscope",
        "langchain",
        "llama-index",
        "llamaindex",
    }
    provider_modules = {
        path.stem
        for path in PROVIDERS_ROOT.glob("*.py")
        if path.stem != "__init__"
    }

    forbidden_installed = {
        distribution
        for distribution in installed_names
        if any(
            distribution == forbidden
            or distribution.startswith(f"{forbidden}-")
            for forbidden in forbidden_distributions
        )
    }

    assert forbidden_installed == set()
    assert provider_modules == {"deepseek", "mock", "openai"}


def test_llm_public_dtos_do_not_expose_http_or_supplier_types() -> None:
    dto_paths = sorted(LLM_SCHEMA_ROOT.glob("*.py")) + [CHAT_SCHEMA_PATH]
    forbidden_imports = (
        "httpx",
        "openai",
        "deepseek",
        "anthropic",
        "google.generativeai",
        "google.genai",
        "dashscope",
        "langchain",
        "llama_index",
    )
    forbidden_type_names = (
        "httpx.Request",
        "httpx.Response",
        "OpenAIResponse",
        "DeepSeekResponse",
        "SDKResponse",
    )

    for source_path in dto_paths:
        _assert_no_forbidden_imports(source_path, forbidden_imports)
        source = source_path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden_type_names), source_path


def test_llm_service_and_public_package_do_not_depend_on_adapters() -> None:
    _assert_no_forbidden_imports(
        LLM_SERVICE_PATH,
        (
            "fastapi",
            "sqlalchemy",
            "redis",
            "httpx",
            "app.api",
            "app.db",
            "app.models",
            "app.repositories",
            "app.services",
            "app.llm.providers",
            "app.llm.registry",
            "app.llm.factory",
            "app.llm.bootstrap",
        ),
    )
    public_source = LLM_PUBLIC_INIT_PATH.read_text(encoding="utf-8")
    for adapter_symbol in (
        "MockProvider",
        "DeepSeekProvider",
        "OpenAIProvider",
    ):
        assert adapter_symbol not in public_source


def test_llm_http_boundary_has_no_upper_layer_or_supplier_dependency() -> None:
    forbidden_imports = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.llm.providers",
        "openai",
        "deepseek",
        "anthropic",
        "langchain",
        "llama_index",
    )

    for source_path in LLM_HTTP_ROOT.glob("*.py"):
        _assert_no_forbidden_imports(source_path, forbidden_imports)


def test_provider_adapters_do_not_depend_on_upper_or_persistence_layers() -> None:
    forbidden_imports = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
    )

    for source_path in PROVIDERS_ROOT.glob("*.py"):
        _assert_no_forbidden_imports(source_path, forbidden_imports)


def test_readiness_remains_database_only_and_has_no_llm_probe() -> None:
    source = SYSTEM_ROUTE_PATH.read_text(encoding="utf-8")
    tree = _syntax_tree(SYSTEM_ROUTE_PATH)
    ready_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "ready"
    )
    ready_source = ast.unparse(ready_function).lower()

    _assert_no_forbidden_imports(
        SYSTEM_ROUTE_PATH,
        ("app.llm", "httpx", "openai", "deepseek"),
    )
    assert "database_manager.check_connection" in ready_source
    assert not any(
        token in ready_source
        for token in ("llm", "provider", "generate", "remote_probe")
    )
    assert '@router.get("/ready"' in source


def test_persistence_layer_has_no_reverse_dependency_on_llm() -> None:
    persistence_paths = [
        path
        for root in PERSISTENCE_ROOTS
        for path in root.rglob("*.py")
    ]

    assert persistence_paths
    for source_path in persistence_paths:
        _assert_no_forbidden_imports(
            source_path,
            (
                "app.llm",
                "app.services",
                "app.api",
                "httpx",
                "openai",
                "deepseek",
            ),
        )


def test_factory_provider_creation_has_no_supplier_conditionals() -> None:
    syntax_tree = _syntax_tree(FACTORY_PATH)
    factory_class = next(
        node
        for node in syntax_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProviderFactory"
    )
    create_method = next(
        node
        for node in factory_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "create"
    )
    conditional_nodes = tuple(
        node
        for node in ast.walk(create_method)
        if isinstance(node, (ast.If, ast.IfExp, ast.Match))
    )

    assert conditional_nodes == ()
    assert "get_constructor" in ast.unparse(create_method)


def test_public_http_route_paths_and_methods_are_stable() -> None:
    application = FastAPI()
    application.include_router(api_router)
    openapi_paths = application.openapi()["paths"]
    routes = {
        path: frozenset(method.upper() for method in operations)
        for path, operations in openapi_paths.items()
    }

    assert routes == {
        "/health": frozenset({"GET"}),
        "/ready": frozenset({"GET"}),
        "/version": frozenset({"GET"}),
        "/api/v1/chat/completions": frozenset({"POST"}),
    }
    api_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (APP_ROOT / "api").rglob("*.py")
    )
    assert "WebSocket" not in api_source


def test_mock_bootstrap_requires_no_vendor_api_key() -> None:
    settings = LLMSettings(
        _env_file=None,
        provider="mock",
        default_model="architecture-mock-model",
        timeout_seconds=30,
        default_temperature=0.7,
        default_max_tokens=1024,
        openai_api_key=None,
        deepseek_api_key=None,
    )

    service = bootstrap_llm(settings)

    assert service.diagnose().provider_name == "mock"
    assert settings.openai_api_key is None
    assert settings.deepseek_api_key is None


def test_real_llm_integration_is_confined_and_safely_marked() -> None:
    integration_paths = {
        path
        for path in LLM_INTEGRATION_ROOT.glob("test_*_integration.py")
    }
    expected_paths = {
        LLM_INTEGRATION_ROOT / "test_deepseek_integration.py",
        LLM_INTEGRATION_ROOT / "test_openai_integration.py",
    }
    marked_tests: set[tuple[Path, str]] = set()

    assert integration_paths == expected_paths
    for source_path in TESTS_ROOT.rglob("*.py"):
        for node in _syntax_tree(source_path).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {
                ast.unparse(decorator) for decorator in node.decorator_list
            }
            if "pytest.mark.llm_integration" in decorators:
                marked_tests.add((source_path, node.name))

    assert marked_tests == {
        (
            LLM_INTEGRATION_ROOT / "test_deepseek_integration.py",
            "test_deepseek_minimal_non_streaming_call",
        ),
        (
            LLM_INTEGRATION_ROOT / "test_deepseek_integration.py",
            "test_deepseek_minimal_streaming_call",
        ),
        (
            LLM_INTEGRATION_ROOT / "test_openai_integration.py",
            "test_openai_minimal_non_streaming_call",
        ),
        (
            LLM_INTEGRATION_ROOT / "test_openai_integration.py",
            "test_openai_minimal_streaming_call",
        ),
    }


def test_real_llm_integration_has_no_upper_or_persistence_dependencies() -> None:
    forbidden_imports = (
        "app.api",
        "app.services",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
    )
    forbidden_source_fragments = (
        "MockProvider",
        "bootstrap_llm",
        "TestClient",
        "/api/v1/chat/completions",
        "pytest.mark.integration",
        "logging.",
        "logger.",
        "print(",
    )

    for source_path in LLM_INTEGRATION_ROOT.glob("test_*_integration.py"):
        _assert_no_forbidden_imports(source_path, forbidden_imports)
        source = source_path.read_text(encoding="utf-8")
        assert not any(
            fragment in source for fragment in forbidden_source_fragments
        ), source_path
        assert 'content="Say hi."' in source
        assert "max_tokens=16" in source


def test_llm_integration_option_and_cost_gate_are_explicit() -> None:
    source = CONFTEST_PATH.read_text(encoding="utf-8")
    manifest = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    markers = manifest["tool"]["pytest"]["ini_options"]["markers"]

    assert '"--run-llm-integration"' in source
    assert '"--run-integration"' in source
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST" in source
    assert "_external_network_is_allowed" in source
    assert any(marker.startswith("llm_integration:") for marker in markers)


def test_postgresql_tests_are_explicit_opt_in_integration_tests() -> None:
    integration_tests: set[str] = set()
    for source_path in POSTGRESQL_TEST_PATHS:
        for node in _syntax_tree(source_path).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            decorator_names = {ast.unparse(decorator) for decorator in node.decorator_list}
            assert "pytest.mark.integration" in decorator_names
            integration_tests.add(node.name)

    assert integration_tests == {
        "test_postgresql_17_connection",
        "test_ready_with_postgresql",
        "test_alembic_upgrade_reaches_head",
        "test_base_repository_crud",
    }

    all_marked_integration_tests = {
        node.name
        for source_path in TESTS_ROOT.rglob("*.py")
        for node in _syntax_tree(source_path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "pytest.mark.integration"
        in {ast.unparse(decorator) for decorator in node.decorator_list}
    }
    assert all_marked_integration_tests == integration_tests
