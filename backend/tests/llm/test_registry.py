"""Unit tests for the explicit LLM provider registry."""

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from app.llm import ProviderConfigurationError, ProviderNotRegistered
from app.llm.providers import MockProvider
from app.llm.registry import ProviderConstructor, ProviderRegistry


def test_register_normalizes_name_without_constructing_provider() -> None:
    construction_count = 0

    def constructor() -> MockProvider:
        nonlocal construction_count
        construction_count += 1
        return MockProvider()

    registry = ProviderRegistry()

    registration = registry.register("  MoCk_Provider  ", constructor)

    assert registration.name == "mock_provider"
    assert registration.constructor is constructor
    assert registry.get_registration("MOCK_PROVIDER") is registration
    assert registry.get_constructor(" mock_provider ") is constructor
    assert construction_count == 0
    assert len(registry) == 1


def test_registration_metadata_is_immutable() -> None:
    registry = ProviderRegistry()
    registration = registry.register("mock", MockProvider)

    with pytest.raises(FrozenInstanceError):
        setattr(registration, "name", "changed")


def test_provider_names_and_registrations_have_stable_order() -> None:
    registry = ProviderRegistry()
    qwen = registry.register("qwen", MockProvider)
    claude = registry.register("claude", MockProvider)
    gemini = registry.register("gemini", MockProvider)

    assert registry.provider_names == ("claude", "gemini", "qwen")
    assert registry.registrations == (claude, gemini, qwen)


def test_duplicate_registration_is_detected_after_normalization() -> None:
    registry = ProviderRegistry()
    registry.register("Mock", MockProvider)

    with pytest.raises(ProviderConfigurationError) as raised:
        registry.register(" mock ", lambda: MockProvider())

    assert raised.value.provider_name == "mock"
    assert registry.get_constructor("mock") is MockProvider
    assert len(registry) == 1


def test_unknown_provider_raises_normalized_registry_error() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotRegistered) as raised:
        registry.get_registration(" Missing-Provider ")

    assert raised.value.provider_name == "missing-provider"
    assert raised.value.code == "provider_not_registered"


@pytest.mark.parametrize(
    "provider_name",
    (
        "",
        "   ",
        "1openai",
        "-openai",
        "openai-",
        "open ai",
        "openai.provider",
        "openai__backup",
        "openai/backup",
        "a" * 65,
    ),
)
def test_invalid_provider_name_is_rejected(provider_name: str) -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderConfigurationError):
        registry.register(provider_name, MockProvider)

    assert len(registry) == 0


def test_non_callable_constructor_is_rejected() -> None:
    registry = ProviderRegistry()
    invalid_constructor = cast(ProviderConstructor, object())

    with pytest.raises(ProviderConfigurationError) as raised:
        registry.register("mock", invalid_constructor)

    assert raised.value.provider_name == "mock"
    assert len(registry) == 0


def test_registry_instances_do_not_share_mutable_state() -> None:
    first_registry = ProviderRegistry()
    second_registry = ProviderRegistry()
    first_registry.register("mock", MockProvider)

    assert first_registry.provider_names == ("mock",)
    assert second_registry.provider_names == ()
    with pytest.raises(ProviderNotRegistered):
        second_registry.get_constructor("mock")


def test_frozen_registry_remains_queryable_and_rejects_registration() -> None:
    registry = ProviderRegistry()
    registration = registry.register("mock", MockProvider)

    registry.freeze()
    registry.freeze()

    assert registry.is_frozen is True
    assert registry.get_registration("mock") is registration
    with pytest.raises(ProviderConfigurationError):
        registry.register("another-provider", MockProvider)
    assert registry.provider_names == ("mock",)
