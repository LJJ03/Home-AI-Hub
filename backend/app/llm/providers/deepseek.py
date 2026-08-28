"""DeepSeek Chat Completions adapter for normalized text generation."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from typing import Any, NoReturn

import httpx
from pydantic import ValidationError

from app.llm.config import LLMSettings
from app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidResponse,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.http.client import LLMHTTPClient, build_bearer_auth_headers
from app.llm.http.sse import SSEProtocolError, parse_sse
from app.llm.schemas import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenUsage,
)


_PROVIDER_NAME = "deepseek"
_CHAT_COMPLETIONS_PATH = "chat/completions"
_UNSUPPORTED_FINISH_REASONS = {"tool_calls", "function_call"}


class DeepSeekProvider:
    """Adapt DeepSeek HTTP payloads to the frozen provider contract."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        http_client: LLMHTTPClient | None = None,
    ) -> None:
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        default_model = settings.deepseek_default_model

        if api_key is None:
            self._raise_configuration_error("API key")
        if base_url is None:
            self._raise_configuration_error("base URL")
        if default_model is None:
            self._raise_configuration_error("default model")

        headers: httpx.Headers | None = None
        credentials_error: ProviderConfigurationError | None = None
        try:
            headers = build_bearer_auth_headers(api_key)
        except ProviderConfigurationError:
            credentials_error = ProviderConfigurationError(
                "DeepSeek provider credentials are invalid",
                provider_name=_PROVIDER_NAME,
            )
        if credentials_error is not None or headers is None:
            if credentials_error is None:
                credentials_error = ProviderConfigurationError(
                    "DeepSeek provider credentials are invalid",
                    provider_name=_PROVIDER_NAME,
                )
            raise credentials_error
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        self._default_model = default_model
        self._default_temperature = settings.default_temperature
        self._default_max_tokens = settings.default_max_tokens
        self._endpoint = httpx.URL(
            f"{str(base_url).rstrip('/')}/{_CHAT_COMPLETIONS_PATH}"
        )
        self._headers = headers
        self._http_client = http_client or LLMHTTPClient(settings)

    @property
    def provider_name(self) -> str:
        """Return the stable registry name for this adapter."""

        return _PROVIDER_NAME

    @property
    def default_model(self) -> str:
        """Return the configured DeepSeek default model."""

        return self._default_model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one normalized response through DeepSeek HTTP."""

        request_model, payload = self._build_request_payload(
            request,
            stream=False,
        )

        response: httpx.Response | None = None
        transport_error: ProviderTimeout | ProviderUnavailable | None = None
        try:
            response = await self._http_client.request(
                "POST",
                self._endpoint,
                headers=self._headers,
                json=payload,
            )
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException:
            transport_error = ProviderTimeout(
                "DeepSeek request timed out",
                provider_name=self.provider_name,
            )
        except httpx.RequestError:
            transport_error = ProviderUnavailable(
                "DeepSeek provider is unavailable",
                provider_name=self.provider_name,
            )

        if transport_error is not None:
            raise transport_error
        if response is None:
            raise ProviderUnavailable(
                "DeepSeek provider is unavailable",
                provider_name=self.provider_name,
            )

        self._raise_for_http_status(response)
        return self._map_response(response, request_model=request_model)

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Stream normalized chunks without retaining the completed output."""

        return self._stream_response(request)

    async def aclose(self) -> None:
        """Release the provider-owned HTTP client idempotently."""

        await self._http_client.aclose()

    async def _stream_response(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMStreamChunk]:
        request_model, payload = self._build_request_payload(
            request,
            stream=True,
        )
        transport_error: (
            ProviderInvalidResponse | ProviderTimeout | ProviderUnavailable | None
        ) = None
        stream_headers = self._headers.copy()
        stream_headers["Accept"] = "text/event-stream"

        try:
            async with self._http_client.stream(
                "POST",
                self._endpoint,
                headers=stream_headers,
                json=payload,
            ) as response:
                self._raise_for_http_status(response)
                async for chunk in self._map_stream(
                    response,
                    request_model=request_model,
                ):
                    yield chunk
        except asyncio.CancelledError:
            raise
        except SSEProtocolError:
            transport_error = self._invalid_response()
        except httpx.TimeoutException:
            transport_error = ProviderTimeout(
                "DeepSeek request timed out",
                provider_name=self.provider_name,
            )
        except httpx.HTTPError:
            transport_error = ProviderUnavailable(
                "DeepSeek provider is unavailable",
                provider_name=self.provider_name,
            )

        if transport_error is not None:
            raise transport_error

    async def _map_stream(
        self,
        response: httpx.Response,
        *,
        request_model: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        events = parse_sse(response.aiter_bytes())
        sequence = 0
        response_model: str | None = None
        provider_request_id: str | None = None
        finish_reason: FinishReason | None = None
        usage: TokenUsage | None = None

        try:
            async for event in events:
                if event.is_done:
                    if finish_reason is None:
                        raise self._invalid_response()

                    yield self._build_stream_chunk(
                        sequence=sequence,
                        delta="",
                        model_name=response_model or request_model,
                        provider_request_id=provider_request_id,
                        is_final=True,
                        finish_reason=finish_reason,
                        usage=usage,
                    )
                    return

                payload = self._decode_stream_payload(event.data)
                response_model = self._merge_stream_identity(
                    current=response_model,
                    incoming=payload.get("model"),
                )
                provider_request_id = self._merge_stream_identity(
                    current=provider_request_id,
                    incoming=payload.get("id"),
                )

                if "usage" in payload and payload["usage"] is not None:
                    usage = self._map_usage(payload["usage"])

                choices = payload.get("choices")
                if not isinstance(choices, list):
                    raise self._invalid_response()
                if not choices:
                    if payload.get("usage") is None:
                        raise self._invalid_response()
                    continue
                if len(choices) != 1 or not isinstance(choices[0], dict):
                    raise self._invalid_response()

                choice = choices[0]
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    raise self._invalid_response()
                if any(
                    field in delta
                    for field in ("tool_calls", "tool_call", "function_call")
                ):
                    raise self._invalid_response()

                incoming_finish_reason = choice.get("finish_reason")
                if incoming_finish_reason is not None:
                    normalized_finish_reason = self._map_finish_reason(
                        incoming_finish_reason
                    )
                    if (
                        finish_reason is not None
                        and finish_reason is not normalized_finish_reason
                    ):
                        raise self._invalid_response()
                    finish_reason = normalized_finish_reason

                content = delta.get("content")
                if content is None or content == "":
                    continue
                if not isinstance(content, str):
                    raise self._invalid_response()

                yield self._build_stream_chunk(
                    sequence=sequence,
                    delta=content,
                    model_name=response_model or request_model,
                    provider_request_id=provider_request_id,
                )
                sequence += 1

            raise self._invalid_response()
        finally:
            await events.aclose()

    def _build_request_payload(
        self,
        request: LLMRequest,
        *,
        stream: bool,
    ) -> tuple[str, dict[str, Any]]:
        request_model = request.model_name or self.default_model
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in request.messages
            ],
            "model": request_model,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self._default_temperature
            ),
            "max_tokens": (
                request.max_tokens
                if request.max_tokens is not None
                else self._default_max_tokens
            ),
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return request_model, payload

    def _decode_stream_payload(self, data: str) -> dict[str, Any]:
        payload: Any = None
        invalid_json = False
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            invalid_json = True
        if invalid_json or not isinstance(payload, dict):
            raise self._invalid_response()
        return payload

    def _merge_stream_identity(
        self,
        *,
        current: str | None,
        incoming: Any,
    ) -> str | None:
        if incoming is None:
            return current
        if not isinstance(incoming, str) or not incoming.strip():
            raise self._invalid_response()
        if current is not None and incoming != current:
            raise self._invalid_response()
        return incoming

    def _build_stream_chunk(
        self,
        *,
        sequence: int,
        delta: str,
        model_name: str,
        provider_request_id: str | None,
        is_final: bool = False,
        finish_reason: FinishReason | None = None,
        usage: TokenUsage | None = None,
    ) -> LLMStreamChunk:
        chunk: LLMStreamChunk | None = None
        invalid_contract = False
        try:
            chunk = LLMStreamChunk(
                sequence=sequence,
                delta=delta,
                provider_name=self.provider_name,
                model_name=model_name,
                is_final=is_final,
                finish_reason=finish_reason,
                usage=usage,
                provider_request_id=provider_request_id,
            )
        except ValidationError:
            invalid_contract = True
        if invalid_contract or chunk is None:
            raise self._invalid_response()
        return chunk

    def _raise_for_http_status(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if 200 <= status_code < 300:
            return

        if status_code in {401, 403}:
            raise ProviderAuthenticationError(
                "DeepSeek authentication failed",
                provider_name=self.provider_name,
            )
        if status_code == 408:
            raise ProviderTimeout(
                "DeepSeek request timed out",
                provider_name=self.provider_name,
            )
        if status_code == 429:
            raise ProviderRateLimitError(
                "DeepSeek request was rate limited",
                provider_name=self.provider_name,
                retry_after_seconds=self._parse_retry_after(response),
            )
        if status_code in {400, 402, 404, 422} or 400 <= status_code < 500:
            raise ProviderConfigurationError(
                "DeepSeek rejected the request configuration",
                provider_name=self.provider_name,
            )

        raise ProviderUnavailable(
            "DeepSeek provider is unavailable",
            provider_name=self.provider_name,
        )

    def _map_response(
        self,
        response: httpx.Response,
        *,
        request_model: str,
    ) -> LLMResponse:
        payload: Any = None
        invalid_json = False
        try:
            payload = response.json()
        except ValueError:
            invalid_json = True
        if invalid_json:
            raise self._invalid_response()

        if not isinstance(payload, dict):
            raise self._invalid_response()

        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise self._invalid_response()

        choice = choices[0]
        if not isinstance(choice, dict):
            raise self._invalid_response()

        message = choice.get("message")
        if not isinstance(message, dict):
            raise self._invalid_response()
        if "tool_calls" in message or "function_call" in message:
            raise self._invalid_response()

        content = message.get("content")
        if not isinstance(content, str):
            raise self._invalid_response()

        finish_reason = self._map_finish_reason(choice.get("finish_reason"))
        response_model = payload.get("model")
        if response_model is None:
            model_name = request_model
        elif isinstance(response_model, str) and response_model.strip():
            model_name = response_model
        else:
            raise self._invalid_response()

        provider_request_id = payload.get("id")
        if provider_request_id is not None and (
            not isinstance(provider_request_id, str)
            or not provider_request_id.strip()
        ):
            raise self._invalid_response()

        usage = self._map_usage(payload.get("usage"))
        normalized_response: LLMResponse | None = None
        invalid_contract = False
        try:
            normalized_response = LLMResponse(
                text=content,
                provider_name=self.provider_name,
                model_name=model_name,
                finish_reason=finish_reason,
                usage=usage,
                provider_request_id=provider_request_id,
            )
        except ValidationError:
            invalid_contract = True
        if invalid_contract or normalized_response is None:
            raise self._invalid_response()
        return normalized_response

    def _map_finish_reason(self, value: Any) -> FinishReason:
        if not isinstance(value, str) or not value.strip():
            raise self._invalid_response()
        if value == "stop":
            return FinishReason.STOP
        if value == "length":
            return FinishReason.LENGTH
        if value == "content_filter":
            return FinishReason.CONTENT_FILTER
        if value == "insufficient_system_resource":
            raise ProviderUnavailable(
                "DeepSeek provider has insufficient capacity",
                provider_name=self.provider_name,
            )
        if value in _UNSUPPORTED_FINISH_REASONS:
            raise self._invalid_response()
        return FinishReason.UNKNOWN

    def _map_usage(self, value: Any) -> TokenUsage | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise self._invalid_response()

        usage: TokenUsage | None = None
        invalid_usage = False
        try:
            usage = TokenUsage(
                input_tokens=value.get("prompt_tokens"),
                output_tokens=value.get("completion_tokens"),
                total_tokens=value.get("total_tokens"),
            )
        except ValidationError:
            invalid_usage = True
        if invalid_usage or usage is None:
            raise self._invalid_response()
        return usage

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None

        try:
            parsed = float(value)
        except ValueError:
            return None
        if not math.isfinite(parsed) or parsed < 0:
            return None
        return parsed

    def _invalid_response(self) -> ProviderInvalidResponse:
        return ProviderInvalidResponse(
            "DeepSeek returned an invalid response",
            provider_name=self.provider_name,
        )

    @staticmethod
    def _raise_configuration_error(component: str) -> NoReturn:
        raise ProviderConfigurationError(
            f"DeepSeek provider {component} is required",
            provider_name=_PROVIDER_NAME,
        )


__all__ = ("DeepSeekProvider",)
