"""Unit tests for registry-backed LLM provider creation."""

import ast
from pathlib import Path

import pytest

from app.llm import ProviderConfigurationError, ProviderNotRegistered
from app.llm.config import LLMSettings
from app.llm.factory import ProviderFactory
from app.llm.providers import MockProvider
from app.llm.registry import ProviderRegistry


FACTORY_PATH = Path(__file__).resolve().parents[2] / "app/llm/factory.py"


def _settings(provider: str = "mock") -> LLMSettings:
    values: dict[str, object] = {
        "provider": provider,
        "default_model": "configured-mock-model",
        "timeout_seconds": 30,
        "default_temperature": 0.7,
        "default_max_tokens": 1024,
    }
    if provider in {"deepseek", "openai"}:
        values.update(
            {
                f"{provider}_api_key": f"{provider}-test-secret",
                f"{provider}_base_url": f"https://{provider}.example.test/v1",
                f"{provider}_default_model": f"{provider}-test-model",
            }
        )

    return LLMSettings(
        _env_file=None,
        **values,
    )


def test_factory_creates_provider_from_registered_constructor() -> None:
    construction_count = 0

    def constructor() -> MockProvider:
        nonlocal construction_count
        construction_count += 1
        return MockProvider(default_model="registered-model")

    registry = ProviderRegistry()
    registry.register("mock", constructor)
    registry.freeze()
    factory = ProviderFactory(registry)

    provider = factory.create(_settings())

    assert isinstance(provider, MockProvider)
    assert provider.default_model == "registered-model"
    assert construction_count == 1


def test_factory_requires_frozen_registry() -> None:
    registry = ProviderRegistry()
    registry.register("mock", MockProvider)

    with pytest.raises(ProviderConfigurationError):
        ProviderFactory(registry)


@pytest.mark.parametrize("provider_name", ("deepseek", "openai"))
def test_factory_fails_for_unregistered_provider_without_fallback(
    provider_name: str,
) -> None:
    construction_count = 0

    def mock_constructor() -> MockProvider:
        nonlocal construction_count
        construction_count += 1
        return MockProvider()

    registry = ProviderRegistry()
    registry.register("mock", mock_constructor)
    registry.freeze()
    factory = ProviderFactory(registry)

    with pytest.raises(ProviderNotRegistered) as raised:
        factory.create(_settings(provider_name))

    assert raised.value.provider_name == provider_name
    assert construction_count == 0


def test_factory_remains_supplier_neutral_and_registry_driven() -> None:
    tree = ast.parse(
        FACTORY_PATH.read_text(encoding="utf-8"),
        filename=str(FACTORY_PATH),
    )
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    factory_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProviderFactory"
    )
    create_method = next(
        node
        for node in factory_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "create"
    )

    assert not any(module.startswith("app.llm.providers") for module in imports)
    assert imports.isdisjoint({"os", "pydantic_settings"})
    assert not any(
        isinstance(node, (ast.If, ast.IfExp, ast.Match))
        for node in ast.walk(create_method)
    )
    assert "get_constructor" in ast.unparse(create_method)
    source = FACTORY_PATH.read_text(encoding="utf-8").lower()
    assert "fallback" not in source
    assert "retry" not in source
    assert "routing" not in source
