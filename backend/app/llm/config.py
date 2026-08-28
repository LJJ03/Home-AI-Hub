"""Independent environment-backed configuration for the LLM provider layer."""

from typing import Self

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.exceptions import ProviderConfigurationError


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class LLMSettings(BaseSettings):
    """Load and validate vendor-neutral LLM runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
        env_ignore_empty=True,
    )

    provider: str = Field(
        min_length=1,
        max_length=64,
        validation_alias="LLM_PROVIDER",
    )
    default_model: str = Field(
        min_length=1,
        max_length=255,
        validation_alias="LLM_DEFAULT_MODEL",
    )
    timeout_seconds: float = Field(
        gt=0,
        allow_inf_nan=False,
        validation_alias="LLM_TIMEOUT_SECONDS",
    )
    connect_timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        validation_alias="LLM_CONNECT_TIMEOUT_SECONDS",
    )
    read_timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        validation_alias="LLM_READ_TIMEOUT_SECONDS",
    )
    stream_timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        validation_alias="LLM_STREAM_TIMEOUT_SECONDS",
    )
    default_temperature: float = Field(
        ge=0,
        le=2,
        allow_inf_nan=False,
        validation_alias="LLM_DEFAULT_TEMPERATURE",
    )
    default_max_tokens: int = Field(
        ge=1,
        validation_alias="LLM_DEFAULT_MAX_TOKENS",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_default_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias="OPENAI_DEFAULT_MODEL",
    )
    openai_base_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias="OPENAI_BASE_URL",
    )
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
    )
    deepseek_default_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias="DEEPSEEK_DEFAULT_MODEL",
    )
    deepseek_base_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias="DEEPSEEK_BASE_URL",
    )

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        """Normalize configured provider names without deciding availability."""

        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "default_model",
        "openai_default_model",
        "deepseek_default_model",
        mode="before",
    )
    @classmethod
    def normalize_default_model(cls, value: object) -> object:
        """Remove accidental surrounding whitespace from model names."""

        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("openai_base_url", "deepseek_base_url", mode="before")
    @classmethod
    def validate_provider_base_url(cls, value: object) -> AnyHttpUrl | None:
        """Validate and normalize an explicitly configured provider endpoint."""

        if value is None:
            return None

        try:
            url = _HTTP_URL_ADAPTER.validate_python(value)
        except ValidationError:
            raise ProviderConfigurationError(
                "Provider base URL must be a valid HTTPS URL"
            ) from None

        if url.scheme.lower() != "https":
            raise ProviderConfigurationError(
                "Provider base URL must use HTTPS"
            )
        if url.username is not None or url.password is not None:
            raise ProviderConfigurationError(
                "Provider base URL must not contain user information"
            )
        if url.query is not None:
            raise ProviderConfigurationError(
                "Provider base URL must not contain a query string"
            )
        if url.fragment is not None:
            raise ProviderConfigurationError(
                "Provider base URL must not contain a fragment"
            )

        normalized_url = f"{str(url).rstrip('/')}/"
        return _HTTP_URL_ADAPTER.validate_python(normalized_url)

    @model_validator(mode="after")
    def apply_defaults_and_validate_selected_provider(self) -> Self:
        """Resolve timeouts and fail fast for an incomplete selected provider."""

        for field_name in (
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "stream_timeout_seconds",
        ):
            if getattr(self, field_name) is None:
                object.__setattr__(self, field_name, self.timeout_seconds)

        if self.provider == "openai":
            self._require_selected_provider_configuration(
                provider_name="openai",
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                default_model=self.openai_default_model,
            )
        elif self.provider == "deepseek":
            self._require_selected_provider_configuration(
                provider_name="deepseek",
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                default_model=self.deepseek_default_model,
            )

        return self

    @staticmethod
    def _require_selected_provider_configuration(
        *,
        provider_name: str,
        api_key: SecretStr | None,
        base_url: AnyHttpUrl | None,
        default_model: str | None,
    ) -> None:
        """Require only the credentials selected by the deployment configuration."""

        display_name = provider_name.capitalize()
        if api_key is None or not api_key.get_secret_value().strip():
            raise ProviderConfigurationError(
                f"{display_name} provider API key is required",
                provider_name=provider_name,
            )
        if base_url is None:
            raise ProviderConfigurationError(
                f"{display_name} provider base URL is required",
                provider_name=provider_name,
            )
        if default_model is None:
            raise ProviderConfigurationError(
                f"{display_name} provider default model is required",
                provider_name=provider_name,
            )


__all__ = ("LLMSettings",)
