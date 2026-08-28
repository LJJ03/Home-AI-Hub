"""Unit tests for independent, environment-backed LLM settings."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.llm.config import LLMSettings


LLM_ENV_KEYS = {
    "LLM_PROVIDER",
    "LLM_DEFAULT_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_CONNECT_TIMEOUT_SECONDS",
    "LLM_READ_TIMEOUT_SECONDS",
    "LLM_STREAM_TIMEOUT_SECONDS",
    "LLM_DEFAULT_TEMPERATURE",
    "LLM_DEFAULT_MAX_TOKENS",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_DEFAULT_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_DEFAULT_MODEL",
}


@pytest.fixture(autouse=True)
def clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent from developer and CI provider credentials."""

    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _valid_settings_values() -> dict[str, object]:
    return {
        "provider": "mock",
        "default_model": "mock-model",
        "timeout_seconds": 30,
        "default_temperature": 0.7,
        "default_max_tokens": 1024,
    }


def _environment_keys(path: Path) -> set[str]:
    return {
        line.split("=", maxsplit=1)[0].strip()
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip())
        and not line.startswith("#")
        and "=" in line
    }


def test_mock_settings_require_no_vendor_credentials() -> None:
    settings = LLMSettings(_env_file=None, **_valid_settings_values())

    assert settings.provider == "mock"
    assert settings.connect_timeout_seconds == 30
    assert settings.read_timeout_seconds == 30
    assert settings.stream_timeout_seconds == 30
    assert settings.openai_api_key is None
    assert settings.openai_base_url is None
    assert settings.openai_default_model is None
    assert settings.deepseek_api_key is None
    assert settings.deepseek_base_url is None
    assert settings.deepseek_default_model is None


def test_settings_load_and_protect_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "LLM_PROVIDER": "  MoCk  ",
        "LLM_DEFAULT_MODEL": "  mock-environment-model  ",
        "LLM_TIMEOUT_SECONDS": "45.5",
        "LLM_CONNECT_TIMEOUT_SECONDS": "2.5",
        "LLM_READ_TIMEOUT_SECONDS": "40",
        "LLM_STREAM_TIMEOUT_SECONDS": "60",
        "LLM_DEFAULT_TEMPERATURE": "0.25",
        "LLM_DEFAULT_MAX_TOKENS": "2048",
        "OPENAI_API_KEY": "openai-test-secret",
        "OPENAI_BASE_URL": "https://openai.example.test/v1",
        "OPENAI_DEFAULT_MODEL": "  openai-test-model  ",
        "DEEPSEEK_API_KEY": "deepseek-test-secret",
        "DEEPSEEK_BASE_URL": "https://deepseek.example.test/v1",
        "DEEPSEEK_DEFAULT_MODEL": "  deepseek-test-model  ",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    settings = LLMSettings(_env_file=None)

    assert settings.provider == "mock"
    assert settings.default_model == "mock-environment-model"
    assert settings.timeout_seconds == 45.5
    assert settings.connect_timeout_seconds == 2.5
    assert settings.read_timeout_seconds == 40
    assert settings.stream_timeout_seconds == 60
    assert settings.default_temperature == 0.25
    assert settings.default_max_tokens == 2048
    assert isinstance(settings.openai_api_key, SecretStr)
    assert isinstance(settings.deepseek_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "openai-test-secret"
    assert settings.deepseek_api_key.get_secret_value() == "deepseek-test-secret"
    assert settings.openai_default_model == "openai-test-model"
    assert settings.deepseek_default_model == "deepseek-test-model"

    rendered_settings = "\n".join(
        (
            repr(settings),
            str(settings),
            repr(settings.model_dump()),
            settings.model_dump_json(),
        )
    )
    assert "openai-test-secret" not in rendered_settings
    assert "deepseek-test-secret" not in rendered_settings


def test_provider_name_is_extensible_and_only_normalized() -> None:
    values = _valid_settings_values()
    values["provider"] = "  ClAuDe  "

    settings = LLMSettings(_env_file=None, **values)

    assert settings.provider == "claude"


def test_missing_provider_fails_without_mock_fallback() -> None:
    values = _valid_settings_values()
    del values["provider"]

    with pytest.raises(ValidationError) as raised:
        LLMSettings(_env_file=None, **values)

    assert "LLM_PROVIDER" in str(raised.value)


def test_blank_provider_fails_without_mock_fallback() -> None:
    values = _valid_settings_values()
    values["provider"] = "   "

    with pytest.raises(ValidationError):
        LLMSettings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("timeout_seconds", 0),
        ("timeout_seconds", float("inf")),
        ("default_temperature", -0.1),
        ("default_temperature", 2.1),
        ("default_max_tokens", 0),
    ),
)
def test_invalid_generation_defaults_fail_fast(
    field_name: str,
    invalid_value: object,
) -> None:
    values = _valid_settings_values()
    values[field_name] = invalid_value

    with pytest.raises(ValidationError):
        LLMSettings(_env_file=None, **values)


def test_env_example_declares_the_complete_llm_contract() -> None:
    env_example_path = Path(__file__).resolve().parents[3] / ".env.example"

    assert LLM_ENV_KEYS <= _environment_keys(env_example_path)
