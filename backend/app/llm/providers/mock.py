"""Deterministic, offline implementation of the LLM provider contract."""

from collections.abc import AsyncIterator
from enum import StrEnum

from app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.interfaces import LLMProvider
from app.llm.schemas import FinishReason, LLMRequest, LLMResponse, LLMStreamChunk


class MockErrorMode(StrEnum):
    """Failures that a mock provider instance can raise deterministically."""

    NONE = "none"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"


class MockProvider(LLMProvider):
    """Provide deterministic LLM responses without external resources."""

    _PROVIDER_NAME = "mock"
    _DEFAULT_MODEL = "mock-model"
    _DEFAULT_RESPONSE_TEXT = "Mock response"
    _STREAM_CHUNK_SIZE = 8

    def __init__(
        self,
        *,
        response_text: str = _DEFAULT_RESPONSE_TEXT,
        default_model: str = _DEFAULT_MODEL,
        error_mode: MockErrorMode = MockErrorMode.NONE,
    ) -> None:
        self._response_text = response_text
        self._default_model = default_model
        self._error_mode = error_mode
        self._recorded_requests: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        """Return the stable name used for normalized mock responses."""

        return self._PROVIDER_NAME

    @property
    def default_model(self) -> str:
        """Return the model used when a request does not override it."""

        return self._default_model

    @property
    def recorded_requests(self) -> tuple[LLMRequest, ...]:
        """Return an immutable snapshot of requests received by this instance."""

        return tuple(self._recorded_requests)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return one deterministic normalized response or configured error."""

        provider_request_id = self._record_request(request)
        self._raise_configured_error(provider_request_id)

        return LLMResponse(
            text=self._response_text,
            provider_name=self.provider_name,
            model_name=request.model_name or self.default_model,
            finish_reason=FinishReason.STOP,
            provider_request_id=provider_request_id,
        )

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Return a deterministic asynchronous stream for the request."""

        provider_request_id = self._record_request(request)
        return self._stream_response(request, provider_request_id)

    async def aclose(self) -> None:
        """Complete the provider lifecycle; the mock owns no resources."""

    def _record_request(self, request: LLMRequest) -> str:
        """Record one invocation and return its predictable request ID."""

        self._recorded_requests.append(request)
        return f"mock-request-{len(self._recorded_requests):06d}"

    def _raise_configured_error(self, provider_request_id: str) -> None:
        """Raise the normalized failure selected for this provider instance."""

        error_context = {
            "provider_name": self.provider_name,
            "provider_request_id": provider_request_id,
        }

        if self._error_mode is MockErrorMode.NONE:
            return
        if self._error_mode is MockErrorMode.TIMEOUT:
            raise ProviderTimeout("Mock provider timed out", **error_context)
        if self._error_mode is MockErrorMode.AUTHENTICATION:
            raise ProviderAuthenticationError(
                "Mock provider authentication failed",
                **error_context,
            )
        if self._error_mode is MockErrorMode.RATE_LIMIT:
            raise ProviderRateLimitError(
                "Mock provider rate limit exceeded",
                retry_after_seconds=1.0,
                **error_context,
            )
        if self._error_mode is MockErrorMode.UNAVAILABLE:
            raise ProviderUnavailable(
                "Mock provider is unavailable",
                **error_context,
            )

        raise AssertionError(f"Unsupported mock error mode: {self._error_mode!r}")

    async def _stream_response(
        self,
        request: LLMRequest,
        provider_request_id: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Yield deterministic content chunks followed by one final chunk."""

        self._raise_configured_error(provider_request_id)
        model_name = request.model_name or self.default_model

        for sequence, start in enumerate(
            range(0, len(self._response_text), self._STREAM_CHUNK_SIZE)
        ):
            yield LLMStreamChunk(
                sequence=sequence,
                delta=self._response_text[start : start + self._STREAM_CHUNK_SIZE],
                provider_name=self.provider_name,
                model_name=model_name,
                provider_request_id=provider_request_id,
            )

        final_sequence = (
            len(self._response_text) + self._STREAM_CHUNK_SIZE - 1
        ) // self._STREAM_CHUNK_SIZE
        yield LLMStreamChunk(
            sequence=final_sequence,
            provider_name=self.provider_name,
            model_name=model_name,
            is_final=True,
            finish_reason=FinishReason.STOP,
            provider_request_id=provider_request_id,
        )


__all__ = ("MockErrorMode", "MockProvider")
