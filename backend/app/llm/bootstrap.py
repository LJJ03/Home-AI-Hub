"""Composition root for the vendor-neutral LLM provider layer."""

from functools import partial

from app.llm.config import LLMSettings
from app.llm.factory import ProviderFactory
from app.llm.providers import DeepSeekProvider, MockProvider, OpenAIProvider
from app.llm.registry import ProviderRegistry
from app.llm.service import LLMService


def bootstrap_llm(settings: LLMSettings) -> LLMService:
    """Compose the configured LLM service for one application instance."""

    registry = ProviderRegistry()
    registry.register(
        "mock",
        partial(MockProvider, default_model=settings.default_model),
    )
    registry.register(
        "deepseek",
        partial(DeepSeekProvider, settings),
    )
    registry.register(
        "openai",
        partial(OpenAIProvider, settings),
    )
    registry.freeze()

    factory = ProviderFactory(registry)
    provider = factory.create(settings)
    return LLMService(provider)


__all__ = ("bootstrap_llm",)
