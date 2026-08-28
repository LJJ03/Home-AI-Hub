"""Explicit registry for available LLM provider constructors."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.llm.exceptions import ProviderConfigurationError, ProviderNotRegistered
from app.llm.interfaces import LLMProvider


type ProviderConstructor = Callable[[], LLMProvider]


_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_MAX_PROVIDER_NAME_LENGTH = 64


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """Describe one normalized provider registration without creating it."""

    name: str
    constructor: ProviderConstructor


class ProviderRegistry:
    """Store provider registrations within one explicitly owned instance."""

    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}
        self._frozen = False

    def register(
        self,
        provider_name: str,
        constructor: ProviderConstructor,
    ) -> ProviderRegistration:
        """Register one constructor under a validated canonical name."""

        if self._frozen:
            raise ProviderConfigurationError(
                "Provider registry is frozen and cannot accept registrations"
            )

        normalized_name = _normalize_provider_name(provider_name)
        if not callable(constructor):
            raise ProviderConfigurationError(
                "Provider constructor must be callable",
                provider_name=normalized_name,
            )
        if normalized_name in self._registrations:
            raise ProviderConfigurationError(
                f"LLM provider '{normalized_name}' is already registered",
                provider_name=normalized_name,
            )

        registration = ProviderRegistration(
            name=normalized_name,
            constructor=constructor,
        )
        self._registrations[normalized_name] = registration
        return registration

    def get_registration(self, provider_name: str) -> ProviderRegistration:
        """Return immutable registration metadata for one provider name."""

        normalized_name = _normalize_provider_name(provider_name)
        try:
            return self._registrations[normalized_name]
        except KeyError as error:
            raise ProviderNotRegistered(
                f"LLM provider '{normalized_name}' is not registered",
                provider_name=normalized_name,
            ) from error

    def get_constructor(self, provider_name: str) -> ProviderConstructor:
        """Return a provider constructor without invoking it."""

        return self.get_registration(provider_name).constructor

    def freeze(self) -> None:
        """Permanently close this registry instance to further registration."""

        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """Return whether registration has been permanently disabled."""

        return self._frozen

    @property
    def provider_names(self) -> tuple[str, ...]:
        """Return registered provider names in stable lexical order."""

        return tuple(sorted(self._registrations))

    @property
    def registrations(self) -> tuple[ProviderRegistration, ...]:
        """Return an immutable, stably ordered snapshot of registrations."""

        return tuple(
            self._registrations[name]
            for name in sorted(self._registrations)
        )

    def __len__(self) -> int:
        """Return the number of registered providers."""

        return len(self._registrations)


def _normalize_provider_name(provider_name: str) -> str:
    """Normalize and validate one public provider identifier."""

    if not isinstance(provider_name, str):
        raise ProviderConfigurationError("Provider name must be a string")

    normalized_name = provider_name.strip().lower()
    if (
        len(normalized_name) > _MAX_PROVIDER_NAME_LENGTH
        or _PROVIDER_NAME_PATTERN.fullmatch(normalized_name) is None
    ):
        raise ProviderConfigurationError(
            "Provider name must be 1-64 ASCII characters and contain only "
            "lowercase letters, digits, single hyphens, or single underscores; "
            "it must start with a letter and end with a letter or digit"
        )
    return normalized_name


__all__ = (
    "ProviderConstructor",
    "ProviderRegistration",
    "ProviderRegistry",
)
