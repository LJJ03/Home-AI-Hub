"""Composition tests for explicit LLM provider registration and selection."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.llm as public_llm
from app.llm import ProviderConfigurationError, ProviderNotRegistered
from app.llm.bootstrap import bootstrap_llm
from app.llm.config import LLMSettings
from app.llm.http.client import LLMHTTPClient
from app.llm.providers import DeepSeekProvider, MockProvider, OpenAIProvider
from app.llm.registry import ProviderRegistry
from app.llm.service import LLMService


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
BOOTSTRAP_PATH = APP_ROOT / "llm/bootstrap.py"
PROVIDERS_ROOT = APP_ROOT / "llm/providers"


def _settings(provider: str = "mock") -> LLMSettings:
    values: dict[str, object] = {
        "provider": provider,
        "default_model": "bootstrap-mock-model",
        "timeout_seconds": 30,
        "default_temperature": 0.7,
        "default_max_tokens": 1024,
    }
    if provider in {"deepseek", "openai"}:
        values.update(
            {
                f"{provider}_api_key": f"{provider}-bootstrap-test-secret",
                f"{provider}_base_url": (
                    f"https://{provider}-bootstrap.example.test/v1"
                ),
                f"{provider}_default_model": f"{provider}-bootstrap-model",
            }
        )

    return LLMSettings(
        _env_file=None,
        **values,
    )


@pytest.mark.asyncio
async def test_bootstrap_registers_all_providers_before_freezing_registry() -> None:
    registries: list[ProviderRegistry] = []

    class RecordingRegistry(ProviderRegistry):
        def __init__(self) -> None:
            super().__init__()
            registries.append(self)

    with patch("app.llm.bootstrap.ProviderRegistry", RecordingRegistry):
        service = bootstrap_llm(_settings())

    try:
        assert isinstance(service, LLMService)
        assert registries[0].provider_names == ("deepseek", "mock", "openai")
        assert registries[0].is_frozen is True
        with pytest.raises(ProviderConfigurationError):
            registries[0].register("another", MockProvider)
    finally:
        await service.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_name", "provider_type", "expected_model"),
    (
        ("mock", MockProvider, "bootstrap-mock-model"),
        ("deepseek", DeepSeekProvider, "deepseek-bootstrap-model"),
        ("openai", OpenAIProvider, "openai-bootstrap-model"),
    ),
)
async def test_bootstrap_selects_exact_configured_provider_without_network(
    provider_name: str,
    provider_type: type[MockProvider | DeepSeekProvider | OpenAIProvider],
    expected_model: str,
) -> None:
    with (
        patch.object(
            LLMHTTPClient,
            "request",
            new_callable=AsyncMock,
        ) as request,
        patch.object(LLMHTTPClient, "stream") as stream,
    ):
        service = bootstrap_llm(_settings(provider_name))

    try:
        diagnostics = service.diagnose()
        assert isinstance(service._provider, provider_type)
        assert diagnostics.provider_name == provider_name
        assert diagnostics.default_model == expected_model
        request.assert_not_awaited()
        stream.assert_not_called()
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_mock_selection_does_not_construct_real_providers() -> None:
    with (
        patch("app.llm.bootstrap.DeepSeekProvider") as deepseek_constructor,
        patch("app.llm.bootstrap.OpenAIProvider") as openai_constructor,
    ):
        service = bootstrap_llm(_settings())

    try:
        assert service.diagnose().provider_name == "mock"
        deepseek_constructor.assert_not_called()
        openai_constructor.assert_not_called()
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_bootstrap_returns_independent_service_instances() -> None:
    settings = _settings()
    first_service = bootstrap_llm(settings)
    second_service = bootstrap_llm(settings)

    try:
        assert first_service is not second_service
        assert first_service._provider is not second_service._provider
    finally:
        await first_service.aclose()
        await second_service.aclose()


def test_unknown_provider_fails_without_constructing_or_falling_back() -> None:
    with (
        patch("app.llm.bootstrap.MockProvider") as mock_constructor,
        patch("app.llm.bootstrap.DeepSeekProvider") as deepseek_constructor,
        patch("app.llm.bootstrap.OpenAIProvider") as openai_constructor,
        pytest.raises(ProviderNotRegistered) as raised,
    ):
        bootstrap_llm(_settings("unknown-provider"))

    assert raised.value.provider_name == "unknown-provider"
    mock_constructor.assert_not_called()
    deepseek_constructor.assert_not_called()
    openai_constructor.assert_not_called()


@pytest.mark.parametrize("provider_name", ("deepseek", "openai"))
def test_selected_real_provider_configuration_fails_before_bootstrap(
    provider_name: str,
) -> None:
    with pytest.raises(ProviderConfigurationError) as raised:
        LLMSettings(
            _env_file=None,
            provider=provider_name,
            default_model="generic-fallback-model",
            timeout_seconds=30,
            default_temperature=0.7,
            default_max_tokens=1024,
        )

    assert raised.value.provider_name == provider_name


def test_public_llm_package_does_not_export_concrete_providers() -> None:
    assert not hasattr(public_llm, "MockProvider")
    assert not hasattr(public_llm, "DeepSeekProvider")
    assert not hasattr(public_llm, "OpenAIProvider")


def test_bootstrap_is_the_only_external_concrete_provider_composition_root() -> None:
    concrete_provider_names = {
        "MockProvider",
        "DeepSeekProvider",
        "OpenAIProvider",
    }
    unexpected_imports: list[Path] = []

    for source_path in APP_ROOT.rglob("*.py"):
        if source_path == BOOTSTRAP_PATH or PROVIDERS_ROOT in source_path.parents:
            continue
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"),
            filename=str(source_path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "app.llm.providers":
                continue
            if concrete_provider_names.intersection(
                alias.name for alias in node.names
            ):
                unexpected_imports.append(source_path)

    assert unexpected_imports == []
