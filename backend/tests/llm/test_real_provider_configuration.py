"""Contract tests for Phase 6 real-provider configuration boundaries."""

from __future__ import annotations

import logging
import socket
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.llm.config import LLMSettings
from app.llm.exceptions import ProviderConfigurationError


LLM_ENV_KEYS = (
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
)


@pytest.fixture(autouse=True)
def clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every configuration test independent from developer credentials."""

    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _base_values(*, provider: str = "mock") -> dict[str, Any]:
    return {
        "provider": provider,
        "default_model": "fallback-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.2,
        "default_max_tokens": 512,
        "_env_file": None,
    }


def _real_provider_values(provider: str) -> dict[str, Any]:
    values = _base_values(provider=provider)
    values.update(
        {
            f"{provider}_api_key": f"{provider}-test-secret",
            f"{provider}_base_url": f"https://{provider}.example.test/v1",
            f"{provider}_default_model": f"{provider}-test-model",
        }
    )
    return values


def test_mock_requires_no_real_provider_credentials() -> None:
    settings = LLMSettings(**_base_values())

    assert settings.provider == "mock"
    assert settings.openai_api_key is None
    assert settings.deepseek_api_key is None


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
@pytest.mark.parametrize("missing_suffix", ["api_key", "base_url", "default_model"])
def test_selected_real_provider_fails_fast_when_required_value_is_missing(
    provider: str,
    missing_suffix: str,
) -> None:
    values = _real_provider_values(provider)
    values.pop(f"{provider}_{missing_suffix}")

    with pytest.raises(ProviderConfigurationError) as exc_info:
        LLMSettings(**values)

    assert exc_info.value.provider_name == provider
    assert f"{provider}-test-secret" not in str(exc_info.value)


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_api_keys_are_redacted_from_representations_and_logs(
    provider: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"{provider}-never-log-this-secret"
    values = _real_provider_values(provider)
    values[f"{provider}_api_key"] = secret
    settings = LLMSettings(**values)

    logging.getLogger(__name__).warning("settings=%r", settings)
    rendered = "\n".join(
        (
            repr(settings),
            str(settings),
            repr(settings.model_dump()),
            settings.model_dump_json(),
            caplog.text,
        )
    )

    assert secret not in rendered


@pytest.mark.parametrize(
    "invalid_url",
    [
        "https://user:password@openai.example.test/v1",
        "https://openai.example.test/v1?api_key=url-secret",
        "https://openai.example.test/v1#response-fragment",
        "http://openai.example.test/v1",
    ],
)
def test_provider_base_url_rejects_unsafe_components(invalid_url: str) -> None:
    values = _real_provider_values("openai")
    values["openai_base_url"] = invalid_url

    with pytest.raises(ProviderConfigurationError) as exc_info:
        LLMSettings(**values)

    error_text = f"{exc_info.value!s}\n{exc_info.value!r}"
    assert invalid_url not in error_text
    assert "openai-test-secret" not in error_text
    assert "url-secret" not in error_text


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_provider_base_url_is_normalized_to_one_trailing_slash(provider: str) -> None:
    values = _real_provider_values(provider)
    values[f"{provider}_base_url"] = f"https://{provider}.example.test/v1///"

    settings = LLMSettings(**values)

    assert str(getattr(settings, f"{provider}_base_url")) == (
        f"https://{provider}.example.test/v1/"
    )


def test_specialized_timeouts_inherit_legacy_timeout() -> None:
    settings = LLMSettings(**_base_values())

    assert settings.connect_timeout_seconds == settings.timeout_seconds
    assert settings.read_timeout_seconds == settings.timeout_seconds
    assert settings.stream_timeout_seconds == settings.timeout_seconds


def test_specialized_timeouts_can_be_configured_independently() -> None:
    settings = LLMSettings(
        **_base_values(),
        connect_timeout_seconds=2.0,
        read_timeout_seconds=15.0,
        stream_timeout_seconds=45.0,
    )

    assert settings.connect_timeout_seconds == 2.0
    assert settings.read_timeout_seconds == 15.0
    assert settings.stream_timeout_seconds == 45.0


@pytest.mark.parametrize(
    "field_name",
    [
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "stream_timeout_seconds",
    ],
)
@pytest.mark.parametrize("invalid_value", [0, -1, float("inf")])
def test_specialized_timeouts_must_be_positive_and_finite(
    field_name: str,
    invalid_value: float,
) -> None:
    values = _base_values()
    values[field_name] = invalid_value

    with pytest.raises(ValidationError):
        LLMSettings(**values)


def test_constructing_settings_does_not_open_a_network_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect = Mock(side_effect=AssertionError("configuration must stay offline"))
    monkeypatch.setattr(socket, "create_connection", connect)

    LLMSettings(**_real_provider_values("openai"))
    LLMSettings(**_real_provider_values("deepseek"))

    connect.assert_not_called()


def test_httpx_is_runtime_dependency_without_vendor_sdks() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((backend_root / "pyproject.toml").read_text("utf-8"))
    runtime_dependencies = tuple(
        dependency.lower() for dependency in pyproject["project"]["dependencies"]
    )
    optional_dependencies = tuple(
        dependency.lower()
        for group in pyproject["project"].get("optional-dependencies", {}).values()
        for dependency in group
    )
    all_dependencies = runtime_dependencies + optional_dependencies

    assert any(dependency.startswith("httpx") for dependency in runtime_dependencies)
    assert not any(dependency.startswith("openai") for dependency in all_dependencies)
    assert not any(dependency.startswith("deepseek") for dependency in all_dependencies)
