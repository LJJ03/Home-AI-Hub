"""Provider creation through an explicitly supplied frozen registry."""

from app.llm.config import LLMSettings
from app.llm.exceptions import ProviderConfigurationError
from app.llm.interfaces import LLMProvider
from app.llm.registry import ProviderRegistry


class ProviderFactory:
    """Create the configured provider without knowing concrete implementations."""

    def __init__(self, registry: ProviderRegistry) -> None:
        if not registry.is_frozen:
            raise ProviderConfigurationError(
                "Provider registry must be frozen before factory creation"
            )
        self._registry = registry

    def create(self, settings: LLMSettings) -> LLMProvider:
        """Create the provider selected by validated LLM settings."""

        constructor = self._registry.get_constructor(settings.provider)
        return constructor()


__all__ = ("ProviderFactory",)
