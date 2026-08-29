"""Static contracts for Docker Compose runtime topology."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DEV_COMPOSE = PROJECT_ROOT / "docker-compose.dev.yml"
TEST_COMPOSE = PROJECT_ROOT / "docker-compose.test.yml"
PRODUCTION_COMPOSE = PROJECT_ROOT / "docker-compose.production.example.yml"
DOCKER_ENV_EXAMPLE = PROJECT_ROOT / ".env.docker.example"
TEST_ENV_EXAMPLE = PROJECT_ROOT / ".env.test.example"


def _load_compose(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _parse_environment_template(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", maxsplit=1)
        assert key not in values
        values[key] = value
    return values


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command", "")
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


def _healthcheck_text(service: dict[str, Any]) -> str:
    healthcheck = service.get("healthcheck", {})
    test = healthcheck.get("test", "") if isinstance(healthcheck, dict) else ""
    if isinstance(test, list):
        return " ".join(str(part) for part in test)
    return str(test)


def test_base_compose_declares_the_required_services() -> None:
    services = _load_compose(BASE_COMPOSE)["services"]
    assert {"postgres", "redis", "migration", "backend"} <= services.keys()


def test_postgres_17_has_persistent_data_and_healthcheck() -> None:
    compose = _load_compose(BASE_COMPOSE)
    postgres = compose["services"]["postgres"]
    assert str(postgres["image"]).startswith("postgres:17")
    assert "pg_isready" in _healthcheck_text(postgres)
    assert any("postgres_data" in str(volume) for volume in postgres["volumes"])
    assert "postgres_data" in compose["volumes"]


def test_redis_keeps_its_own_healthcheck_without_backend_dependency() -> None:
    compose = _load_compose(BASE_COMPOSE)
    services = compose["services"]
    redis = services["redis"]
    backend_dependencies = services["backend"]["depends_on"]
    assert str(redis["image"]).startswith("redis:8")
    assert "redis-cli ping" in _healthcheck_text(redis)
    assert "redis" not in backend_dependencies


def test_migration_is_one_shot_and_waits_for_healthy_postgres() -> None:
    migration = _load_compose(BASE_COMPOSE)["services"]["migration"]
    assert _command_text(migration) == "python -m alembic upgrade head"
    assert migration["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert migration["restart"] == "no"
    assert migration["healthcheck"]["disable"] is True
    assert "redis" not in migration.get("depends_on", {})


def test_backend_waits_for_postgres_and_successful_migration() -> None:
    backend = _load_compose(BASE_COMPOSE)["services"]["backend"]
    dependencies = backend["depends_on"]
    assert dependencies["postgres"]["condition"] == "service_healthy"
    assert (
        dependencies["migration"]["condition"]
        == "service_completed_successfully"
    )
    command = _command_text(backend).lower()
    assert "alembic" not in command
    assert "pytest" not in command


def test_backend_healthcheck_uses_liveness_not_readiness() -> None:
    backend = _load_compose(BASE_COMPOSE)["services"]["backend"]
    healthcheck = _healthcheck_text(backend)
    assert "/health" in healthcheck
    assert "/ready" not in healthcheck
    assert "redis" not in healthcheck.lower()
    assert "llm" not in healthcheck.lower()


def test_backend_and_migration_share_the_same_image_definition() -> None:
    services = _load_compose(BASE_COMPOSE)["services"]
    backend = services["backend"]
    migration = services["migration"]
    assert backend["image"] == migration["image"]
    assert backend["build"] == migration["build"]


def test_base_compose_is_wired_to_the_docker_environment_profile() -> None:
    services = _load_compose(BASE_COMPOSE)["services"]
    for service_name in ("migration", "backend"):
        env_files = services[service_name]["env_file"]
        assert ".env.docker" in env_files

    environment = _parse_environment_template(DOCKER_ENV_EXAMPLE)
    assert environment["LLM_PROVIDER"] == "mock"
    assert "@postgres:" in environment["DATABASE_URL"]
    assert "@postgres:" in environment["DOCKER_DATABASE_URL"]


def test_compose_contains_no_business_schema_or_provider_secret_value() -> None:
    source = BASE_COMPOSE.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "create_all" not in lowered
    assert "openai_api_key" not in lowered
    assert "deepseek_api_key" not in lowered
    assert "authorization" not in lowered
    assert "llm_provider: deepseek" not in lowered
    assert "llm_provider: openai" not in lowered


def test_development_override_is_nonsecret_and_does_not_enable_provider() -> None:
    source = DEV_COMPOSE.read_text(encoding="utf-8")
    compose = _load_compose(DEV_COMPOSE)
    backend = compose["services"]["backend"]
    assert backend["environment"]["APP_LOG_LEVEL"] == "DEBUG"
    assert "volumes" not in backend
    assert "command" not in backend
    assert "api_key" not in source.lower()
    assert "llm_provider" not in source.lower()


def test_test_compose_uses_an_isolated_postgres_17_service() -> None:
    compose = _load_compose(TEST_COMPOSE)
    services = compose["services"]
    assert set(services) == {"postgres-test"}
    postgres = services["postgres-test"]
    assert str(postgres["image"]).startswith("postgres:17")
    assert "pg_isready" in _healthcheck_text(postgres)
    assert postgres["tmpfs"] == ["/var/lib/postgresql/data"]

    environment = _parse_environment_template(TEST_ENV_EXAMPLE)
    assert "test" in environment["POSTGRES_DB"]
    assert environment["POSTGRES_PORT"] == "5433"
    assert environment["LLM_PROVIDER"] == "mock"
    assert environment["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "false"


def test_production_example_is_nonrunnable_without_platform_injection() -> None:
    source = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    compose = _load_compose(PRODUCTION_COMPOSE)
    services = compose["services"]
    assert {"migration", "backend"} <= services.keys()
    assert "build" not in source
    assert "volumes:" not in source
    assert "reload" not in source.lower()
    assert "api_key" not in source.lower()
    assert "authorization" not in source.lower()
    assert "BACKEND_IMAGE must reference an immutable image" in source
    assert "DATABASE_URL must be injected by the deployment platform" in source
    assert "${LLM_PROVIDER:-mock}" in source
    assert (
        services["backend"]["depends_on"]["migration"]["condition"]
        == "service_completed_successfully"
    )


def test_compose_contract_tests_do_not_require_docker_or_subprocesses() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "docker" not in imported_modules
    assert "subprocess" not in imported_modules
