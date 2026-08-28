"""Offline contracts for environment-template layering and secret safety."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.config import LLMSettings
from app.llm.exceptions import ProviderConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
TEMPLATES = {
    "local": PROJECT_ROOT / ".env.example",
    "docker": PROJECT_ROOT / ".env.docker.example",
    "test": PROJECT_ROOT / ".env.test.example",
    "production": PROJECT_ROOT / ".env.production.example",
}
PROVIDER_SECRET_KEYS = {"OPENAI_API_KEY", "DEEPSEEK_API_KEY"}
PROVIDER_MODEL_KEYS = {
    "OPENAI_DEFAULT_MODEL",
    "DEEPSEEK_DEFAULT_MODEL",
}
COMPOSE_KEYS = {
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "DOCKER_DATABASE_URL",
    "REDIS_PORT",
}
_ENVIRONMENT_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HIGH_RISK_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
)


def _parse_template(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"{path.name}:{line_number} is not KEY=VALUE"
        key, value = line.split("=", maxsplit=1)
        assert _ENVIRONMENT_KEY.fullmatch(key), (
            f"{path.name}:{line_number} has an invalid key"
        )
        assert key not in values, f"{path.name} duplicates {key}"
        values[key] = value
    return values


def _settings_environment_keys() -> set[str]:
    keys: set[str] = set()
    for field_name, field in Settings.model_fields.items():
        alias = field.validation_alias
        keys.add(alias if isinstance(alias, str) else f"APP_{field_name.upper()}")
    return keys


def _llm_environment_keys() -> set[str]:
    keys: set[str] = set()
    for field_name, field in LLMSettings.model_fields.items():
        alias = field.validation_alias
        keys.add(alias if isinstance(alias, str) else field_name.upper())
    return keys


RUNTIME_KEYS = _settings_environment_keys() | _llm_environment_keys()
PROFILE_EXTRA_KEYS = {
    "local": {"LLM_INTEGRATION_ACKNOWLEDGE_COST"},
    "docker": COMPOSE_KEYS,
    "test": {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_PORT",
        "LLM_INTEGRATION_ACKNOWLEDGE_COST",
    },
    "production": set(),
}


@pytest.fixture(autouse=True)
def clear_managed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the developer environment from overriding template assertions."""

    managed_keys = RUNTIME_KEYS | COMPOSE_KEYS | {
        "LLM_INTEGRATION_ACKNOWLEDGE_COST"
    }
    for key in managed_keys:
        monkeypatch.delenv(key, raising=False)


def test_every_environment_template_covers_the_runtime_settings_contract() -> None:
    for profile, path in TEMPLATES.items():
        values = _parse_template(path)
        assert values.keys() == RUNTIME_KEYS | PROFILE_EXTRA_KEYS[profile]


def test_every_environment_template_defaults_to_offline_mock() -> None:
    for path in TEMPLATES.values():
        values = _parse_template(path)
        assert values["LLM_PROVIDER"] == "mock"
        assert all(values[key] == "" for key in PROVIDER_SECRET_KEYS)
        assert all(values[key] == "" for key in PROVIDER_MODEL_KEYS)
        assert values.get("LLM_INTEGRATION_ACKNOWLEDGE_COST") != "true"


def test_nonproduction_templates_load_without_real_provider_configuration() -> None:
    expected_environments = {
        "local": "local",
        "docker": "local",
        "test": "test",
    }
    for profile, expected_environment in expected_environments.items():
        path = TEMPLATES[profile]
        settings = Settings(_env_file=path)
        llm_settings = LLMSettings(_env_file=path)
        assert settings.environment == expected_environment
        assert llm_settings.provider == "mock"
        assert llm_settings.openai_api_key is None
        assert llm_settings.deepseek_api_key is None


def test_production_sample_fails_closed_until_database_secret_is_injected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=TEMPLATES["production"])

    llm_settings = LLMSettings(_env_file=TEMPLATES["production"])
    assert llm_settings.provider == "mock"


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_real_provider_selection_without_secrets_fails_fast(
    provider: str,
) -> None:
    with pytest.raises(ProviderConfigurationError):
        LLMSettings(
            _env_file=TEMPLATES["local"],
            provider=provider,
        )


def test_environment_profiles_keep_scenario_specific_keys_separate() -> None:
    local = _parse_template(TEMPLATES["local"])
    docker = _parse_template(TEMPLATES["docker"])
    test = _parse_template(TEMPLATES["test"])
    production = _parse_template(TEMPLATES["production"])

    assert COMPOSE_KEYS.isdisjoint(local)
    assert COMPOSE_KEYS <= docker.keys()
    assert {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_PORT",
    } <= test.keys()
    assert {"DOCKER_DATABASE_URL", "REDIS_PORT"}.isdisjoint(test)
    assert COMPOSE_KEYS.isdisjoint(production)
    assert local["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "false"
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST" not in docker
    assert test["LLM_INTEGRATION_ACKNOWLEDGE_COST"] == "false"
    assert "LLM_INTEGRATION_ACKNOWLEDGE_COST" not in production


def test_database_hostnames_match_each_profile_boundary() -> None:
    local = _parse_template(TEMPLATES["local"])
    docker = _parse_template(TEMPLATES["docker"])
    test = _parse_template(TEMPLATES["test"])

    assert "@127.0.0.1:" in local["DATABASE_URL"]
    assert "@postgres:" in docker["DATABASE_URL"]
    assert "@postgres:" in docker["DOCKER_DATABASE_URL"]
    assert "@127.0.0.1:" in test["DATABASE_URL"]
    assert ":5433/" in test["DATABASE_URL"]
    assert "home_ai_hub_test" in test["DATABASE_URL"]


def test_local_provider_base_urls_are_explicit_nonsecret_https_configuration() -> None:
    local = _parse_template(TEMPLATES["local"])
    assert local["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert local["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/v1"


def test_templates_contain_no_real_provider_key_or_high_risk_secret_shape() -> None:
    for path in TEMPLATES.values():
        values = _parse_template(path)
        assert all(values[key] == "" for key in PROVIDER_SECRET_KEYS)
        contents = path.read_text(encoding="utf-8")
        assert "Authorization:" not in contents
        assert all(
            pattern.search(contents) is None
            for pattern in _HIGH_RISK_SECRET_PATTERNS
        )


def test_secrets_are_not_embedded_in_docker_build_or_compose_defaults() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for key in PROVIDER_SECRET_KEYS:
        assert key not in dockerfile
        assert key not in compose
    assert "Authorization" not in dockerfile
    assert "Authorization" not in compose


def test_git_and_docker_ignore_real_environment_files() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (BACKEND_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env.*" in gitignore
    assert ".env.*" in dockerignore
    for path in TEMPLATES.values():
        assert f"!{path.name}" in gitignore
