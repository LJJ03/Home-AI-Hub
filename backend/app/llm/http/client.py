"""Provider-neutral asynchronous HTTP transport for the internal LLM layer."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from pydantic import SecretStr

from app.llm.config import LLMSettings
from app.llm.exceptions import ProviderConfigurationError


HeaderValues = Mapping[str, str] | httpx.Headers | None


def build_bearer_auth_headers(api_key: SecretStr) -> httpx.Headers:
    """Build redaction-aware Authorization headers without logging credentials."""

    credential = api_key.get_secret_value()
    if (
        not credential
        or credential != credential.strip()
        or "\r" in credential
        or "\n" in credential
    ):
        raise ProviderConfigurationError(
            "Provider authorization credential is invalid"
        )

    return httpx.Headers({"Authorization": f"Bearer {credential}"})


class LLMHTTPClient:
    """Own one AsyncClient and expose only operations required by providers."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        connect_timeout = self._require_timeout(
            settings.connect_timeout_seconds,
            name="connect",
        )
        read_timeout = self._require_timeout(
            settings.read_timeout_seconds,
            name="read",
        )
        stream_timeout = self._require_timeout(
            settings.stream_timeout_seconds,
            name="stream",
        )

        self._request_timeout = httpx.Timeout(
            timeout=read_timeout,
            connect=connect_timeout,
        )
        self._stream_timeout = httpx.Timeout(
            timeout=stream_timeout,
            connect=connect_timeout,
        )
        self._client = httpx.AsyncClient(
            timeout=self._request_timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    @property
    def request_timeout(self) -> httpx.Timeout:
        """Return the timeout used for complete request/response operations."""

        return self._request_timeout

    @property
    def stream_timeout(self) -> httpx.Timeout:
        """Return the timeout whose read value is stream-event idle time."""

        return self._stream_timeout

    @property
    def is_closed(self) -> bool:
        """Report whether this owner has released its AsyncClient."""

        return self._client.is_closed

    async def request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: HeaderValues = None,
        json: Any = None,
    ) -> httpx.Response:
        """Send one non-streaming request using the configured read timeout."""

        return await self._client.request(
            method,
            url,
            headers=headers,
            json=json,
        )

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: HeaderValues = None,
        json: Any = None,
    ) -> AsyncIterator[httpx.Response]:
        """Open a response stream using event-idle rather than total timeout."""

        async with self._client.stream(
            method,
            url,
            headers=headers,
            json=json,
            timeout=self._stream_timeout,
        ) as response:
            yield response

    async def aclose(self) -> None:
        """Close the owned client exactly once."""

        if self._client.is_closed:
            return

        await self._client.aclose()

    @staticmethod
    def _require_timeout(value: float | None, *, name: str) -> float:
        if value is None:
            raise ProviderConfigurationError(
                f"Provider {name} timeout is not configured"
            )
        return value


__all__ = (
    "LLMHTTPClient",
    "build_bearer_auth_headers",
)
