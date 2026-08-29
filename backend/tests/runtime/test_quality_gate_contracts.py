"""Cross-phase offline quality gates for runtime and release preparation."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
TESTS_ROOT = BACKEND_ROOT / "tests"
DOCS_ROOT = PROJECT_ROOT / "docs"
PYPROJECT = BACKEND_ROOT / "pyproject.toml"
DOCKERFILE = BACKEND_ROOT / "Dockerfile"
BASE_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DOCKER_ENV_EXAMPLE = PROJECT_ROOT / ".env.docker.example"
CONFTEST = TESTS_ROOT / "conftest.py"

FORBIDDEN_SDK_DISTRIBUTIONS = {
    "openai",
    "deepseek",
    "anthropic",
    "google-generativeai",
    "google-genai",
    "dashscope",
    "langchain",
    "llama-index",
    "llamaindex",
    "haystack",
    "haystack-ai",
    "semantic-kernel",
}
FORBIDDEN_SDK_IMPORTS = {
    "openai",
    "deepseek",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "dashscope",
    "langchain",
    "llama_index",
    "llamaindex",
    "haystack",
    "semantic_kernel",
}
SECRET_SHAPE_PATTERNS = {
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "OpenAI-style key": re.compile(
        r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"
    ),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "JWT": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
    "Authorization value": re.compile(
        r"(?i)authorization\s*[:=]\s*[\"']?"
        r"(?:bearer|basic)\s+[A-Za-z0-9+/=_]{24,}"
    ),
    "Cookie value": re.compile(
        r"(?i)\bcookie\s*[:=]\s*[\"']?[A-Za-z0-9+/=_]{32,}"
    ),
}


def _toml() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _syntax_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_syntax_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _normalized_dependency_names() -> set[str]:
    project = _toml()["project"]
    dependency_specs = list(project.get("dependencies", ()))
    for group in project.get("optional-dependencies", {}).values():
        dependency_specs.extend(group)
    return {
        re.split(r"[<>=!~;\[]", specification, maxsplit=1)[0]
        .strip()
        .lower()
        .replace("_", "-")
        for specification in dependency_specs
    }


def _parse_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", maxsplit=1)
        values[key] = value
    return values


def _load_compose() -> dict[str, Any]:
    document = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _files_for_secret_scan() -> tuple[Path, ...]:
    explicit_files = [
        *PROJECT_ROOT.glob(".env*.example"),
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "CHANGELOG.md",
        DOCKERFILE,
        *PROJECT_ROOT.glob("docker-compose*.yml"),
        *PROJECT_ROOT.glob(".github/workflows/*.yml"),
    ]
    recursive_files = [
        *DOCS_ROOT.rglob("*.md"),
        *TESTS_ROOT.rglob("*.py"),
        *APP_ROOT.rglob("*.py"),
    ]
    return tuple(sorted(set(explicit_files + recursive_files)))


def test_python_runtime_is_strictly_python_313() -> None:
    project = _toml()["project"]
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert project["requires-python"] == ">=3.13,<3.14"
    assert sys.version_info[:2] == (3, 13)
    assert re.search(r"(?m)^ARG PYTHON_VERSION=3\.13(?:\.\d+)?$", dockerfile)
    assert dockerfile.count("FROM python:${PYTHON_VERSION}-slim") == 2
    assert not re.search(r"(?im)FROM\s+python:(?:3\.12|3\.14|latest)", dockerfile)


def test_default_pytest_keeps_external_integrations_opt_in() -> None:
    pytest_options = _toml()["tool"]["pytest"]["ini_options"]
    conftest = CONFTEST.read_text(encoding="utf-8")

    assert "--run-integration" not in pytest_options["addopts"]
    assert "--run-llm-integration" not in pytest_options["addopts"]
    assert any(
        marker.startswith("integration:")
        for marker in pytest_options["markers"]
    )
    assert any(
        marker.startswith("llm_integration:")
        for marker in pytest_options["markers"]
    )
    assert 'default=False' in conftest
    assert "block_external_network_by_default" in conftest
    assert "_is_loopback_host" in conftest
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST" in conftest


def test_default_tests_do_not_depend_on_docker_daemon() -> None:
    dependencies = _normalized_dependency_names()
    conftest_imports = _imported_modules(CONFTEST)

    assert "docker" not in dependencies
    assert "docker" not in conftest_imports
    assert "subprocess" not in conftest_imports
    assert (TESTS_ROOT / "test_network_gate.py").is_file()


def test_vendor_sdk_ban_covers_dependencies_and_application_imports() -> None:
    dependencies = _normalized_dependency_names()
    forbidden_dependencies = {
        dependency
        for dependency in dependencies
        if any(
            dependency == forbidden
            or dependency.startswith(f"{forbidden}-")
            for forbidden in FORBIDDEN_SDK_DISTRIBUTIONS
        )
    }
    assert forbidden_dependencies == set()
    assert "httpx" in dependencies

    violations: dict[Path, set[str]] = {}
    for source_path in APP_ROOT.rglob("*.py"):
        imported_modules = _imported_modules(source_path)
        forbidden_imports = {
            module
            for module in imported_modules
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_SDK_IMPORTS
            )
        }
        if forbidden_imports:
            violations[source_path] = forbidden_imports

    assert violations == {}


def test_versioned_artifacts_contain_no_real_secret_shapes() -> None:
    violations: list[str] = []
    for path in _files_for_secret_scan():
        contents = path.read_text(encoding="utf-8")
        for label, pattern in SECRET_SHAPE_PATTERNS.items():
            if pattern.search(contents):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {label}")

    assert violations == []


def test_environment_and_compose_secrets_remain_placeholders() -> None:
    for path in PROJECT_ROOT.glob(".env*.example"):
        environment = _parse_environment(path)
        assert environment["OPENAI_API_KEY"] == ""
        assert environment["DEEPSEEK_API_KEY"] == ""

    production = _parse_environment(PROJECT_ROOT / ".env.production.example")
    compose_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PROJECT_ROOT.glob("docker-compose*.yml")
    )
    assert production["DATABASE_URL"] == ""
    assert "OPENAI_API_KEY" not in compose_sources
    assert "DEEPSEEK_API_KEY" not in compose_sources
    assert "Authorization:" not in compose_sources


def test_application_logging_calls_do_not_include_sensitive_payloads() -> None:
    forbidden_log_fragments = {
        "api_key",
        "authorization",
        "cookie",
        "request.messages",
        "message.content",
        "response.text",
        "chunk.delta",
        "provider_request_id",
    }
    violations: list[str] = []
    for source_path in APP_ROOT.rglob("*.py"):
        for node in ast.walk(_syntax_tree(source_path)):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {
                "debug",
                "info",
                "warning",
                "error",
                "exception",
                "critical",
            }:
                continue
            rendered_call = ast.unparse(node).lower()
            if any(fragment in rendered_call for fragment in forbidden_log_fragments):
                violations.append(
                    f"{source_path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                )

    assert violations == []


def test_docker_and_compose_release_boundaries_remain_separate() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8").lower()
    compose = _load_compose()
    services = compose["services"]
    backend = services["backend"]
    migration = services["migration"]
    docker_environment = _parse_environment(DOCKER_ENV_EXAMPLE)

    assert "copy .env" not in dockerfile
    assert "copy .venv" not in dockerfile
    assert "pytest" not in dockerfile
    assert "alembic upgrade" not in dockerfile
    assert "create_all" not in dockerfile
    assert "alembic upgrade head" in " ".join(migration["command"])
    assert migration["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert (
        backend["depends_on"]["migration"]["condition"]
        == "service_completed_successfully"
    )
    assert "redis" not in backend["depends_on"]
    assert docker_environment["LLM_PROVIDER"] == "mock"


def test_phase_3_to_6_dependency_boundaries_remain_frozen() -> None:
    ready_path = APP_ROOT / "api/routes/system.py"
    chat_route_path = APP_ROOT / "api/v1/routes/chat.py"
    chat_service_path = APP_ROOT / "services/chat.py"
    persistence_paths = [
        path
        for directory in ("db", "models", "repositories")
        for path in (APP_ROOT / directory).rglob("*.py")
    ]

    assert all(
        not module.startswith("app.llm")
        for module in _imported_modules(ready_path)
    )
    assert all(
        not module.startswith("app.llm.providers")
        for module in _imported_modules(chat_route_path)
    )
    assert all(
        not module.startswith("app.llm")
        for path in persistence_paths
        for module in _imported_modules(path)
    )

    llm_service_calls = {
        node.func.attr
        for node in ast.walk(_syntax_tree(chat_service_path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == "_llm_service"
    }
    assert llm_service_calls == {"generate", "stream_generate"}


def test_provider_composition_has_no_automatic_routing_or_retry() -> None:
    factory_path = APP_ROOT / "llm/factory.py"
    bootstrap_path = APP_ROOT / "llm/bootstrap.py"
    provider_paths = (
        APP_ROOT / "llm/providers/deepseek.py",
        APP_ROOT / "llm/providers/openai.py",
    )
    factory_tree = _syntax_tree(factory_path)
    factory_class = next(
        node
        for node in factory_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProviderFactory"
    )
    create_method = next(
        node
        for node in factory_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "create"
    )
    factory_source = factory_path.read_text(encoding="utf-8")
    bootstrap_source = bootstrap_path.read_text(encoding="utf-8")

    assert not any(
        isinstance(node, (ast.If, ast.IfExp, ast.Match))
        for node in ast.walk(create_method)
    )
    assert "get_constructor(settings.provider)" in factory_source
    assert bootstrap_source.count("registry.register(") == 3
    assert bootstrap_source.index("registry.freeze()") < bootstrap_source.index(
        "ProviderFactory(registry)"
    )
    assert bootstrap_source.count("factory.create(settings)") == 1

    retry_dependencies = {"tenacity", "backoff", "retry", "retrying"}
    assert retry_dependencies.isdisjoint(_normalized_dependency_names())
    for provider_path in provider_paths:
        provider_source = provider_path.read_text(encoding="utf-8")
        assert "asyncio.sleep(" not in provider_source
        assert "time.sleep(" not in provider_source


def test_persistence_has_no_create_all_or_business_chat_models() -> None:
    application_source = "\n".join(
        path.read_text(encoding="utf-8") for path in APP_ROOT.rglob("*.py")
    )
    model_tree_nodes = [
        node
        for path in (APP_ROOT / "models").rglob("*.py")
        for node in _syntax_tree(path).body
        if isinstance(node, ast.ClassDef)
    ]

    assert "create_all(" not in application_source
    assert {node.name for node in model_tree_nodes}.isdisjoint(
        {"Chat", "Message", "Conversation", "User"}
    )


def test_documentation_matches_the_current_quality_gate_state() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    docker_doc = (DOCS_ROOT / "operations/docker.md").read_text(encoding="utf-8")
    runtime_doc = (DOCS_ROOT / "operations/runtime.md").read_text(encoding="utf-8")
    environment_doc = (
        DOCS_ROOT / "operations/environment.md"
    ).read_text(encoding="utf-8")
    default_tests_doc = (
        DOCS_ROOT / "testing/default-tests.md"
    ).read_text(encoding="utf-8")
    postgres_doc = (
        DOCS_ROOT / "testing/postgres-integration.md"
    ).read_text(encoding="utf-8")
    llm_doc = (DOCS_ROOT / "testing/llm-integration.md").read_text(
        encoding="utf-8"
    )
    reviewed_docs = "\n".join(
        (
            readme,
            docker_doc,
            runtime_doc,
            environment_doc,
            default_tests_doc,
            postgres_doc,
            llm_doc,
        )
    )
    all_documentation = "\n".join(
        [readme]
        + [
            path.read_text(encoding="utf-8")
            for path in sorted(DOCS_ROOT.rglob("*.md"))
        ]
    )

    assert "cd backend" in readme
    assert "python -m pytest" in readme
    assert "尚未执行" in docker_doc
    assert "动态验证通过" not in runtime_doc
    assert "动态运行验证尚未执行" in runtime_doc
    assert ".env" in environment_doc
    assert "Git ignore" in environment_doc
    assert "零真实 API Key" in default_tests_doc
    assert "零外部网络" in default_tests_doc
    assert "阻断外部 DNS" in default_tests_doc
    assert "--run-integration" in postgres_doc
    assert "--run-llm-integration" in llm_doc
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST=true" in llm_doc
    assert "真实 Integration Tests 已通过" not in reviewed_docs
    assert "PostgreSQL Integration Tests 已通过" not in reviewed_docs
    assert "Phase 7 已冻结" not in all_documentation
    assert (
        "Phase 7 — Runtime, Docker, CI and Release Gate 已冻结（Freeze）。"
        not in all_documentation
    )
    assert (
        "Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending"
        in all_documentation
    )
