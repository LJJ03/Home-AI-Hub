"""Offline tests for the provider-neutral LLM HTTP client boundary."""

from __future__ import annotations

import ast
import logging
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.llm.config import LLMSettings
from app.llm.exceptions import ProviderConfigurationError
from app.llm.http.client import LLMHTTPClient, build_bearer_auth_headers


CLIENT_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "app/llm/http/client.py"
)


def _settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "mock",
        "default_model": "http-client-test-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.2,
        "default_max_tokens": 512,
        "_env_file": None,
    }
    values.update(overrides)
    return LLMSettings(**values)


@pytest.mark.asyncio
async def test_client_uses_injected_mock_transport_without_network() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "offline"})

    client = LLMHTTPClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await client.request(
            "POST",
            "https://provider.example.test/v1/generate",
            json={"input": "local-test"},
        )
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert response.json() == {"status": "offline"}
    assert len(requests) == 1


def test_default_suite_blocks_dns_and_raw_socket_access() -> None:
    message = "External network access is forbidden in default tests"

    with pytest.raises(AssertionError, match=message):
        socket.getaddrinfo("provider.example.test", 443)

    raw_socket = socket.socket()
    try:
        with pytest.raises(AssertionError, match=message):
            raw_socket.connect(("8.8.8.8", 53))
    finally:
        raw_socket.close()


@pytest.mark.asyncio
async def test_request_and_stream_use_their_configured_timeouts() -> None:
    observed_timeouts: list[dict[str, float]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, text="data: ok\n\n")

    client = LLMHTTPClient(
        _settings(
            connect_timeout_seconds=2.0,
            read_timeout_seconds=11.0,
            stream_timeout_seconds=17.0,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.request("GET", "https://provider.example.test/complete")
        async with client.stream(
            "GET",
            "https://provider.example.test/stream",
        ) as response:
            await response.aread()
    finally:
        await client.aclose()

    assert client.request_timeout.connect == 2.0
    assert client.request_timeout.read == 11.0
    assert client.stream_timeout.connect == 2.0
    assert client.stream_timeout.read == 17.0
    assert observed_timeouts[0]["connect"] == 2.0
    assert observed_timeouts[0]["read"] == 11.0
    assert observed_timeouts[1]["connect"] == 2.0
    assert observed_timeouts[1]["read"] == 17.0


@pytest.mark.asyncio
async def test_timeout_values_inherit_the_legacy_timeout() -> None:
    client = LLMHTTPClient(
        _settings(timeout_seconds=23.0),
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
    )

    assert client.request_timeout.connect == 23.0
    assert client.request_timeout.read == 23.0
    assert client.stream_timeout.connect == 23.0
    assert client.stream_timeout.read == 23.0
    await client.aclose()


def test_authorization_header_is_redacted_from_repr_str_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "never-expose-this-bearer-token"
    headers = build_bearer_auth_headers(SecretStr(secret))

    logging.getLogger(__name__).warning(
        "provider_headers repr=%r str=%s",
        headers,
        headers,
    )

    assert headers["Authorization"] == f"Bearer {secret}"
    assert secret not in repr(headers)
    assert secret not in str(headers)
    assert secret not in caplog.text


@pytest.mark.parametrize("credential", ["", " token", "token ", "token\r\n"])
def test_invalid_authorization_credential_fails_safely(credential: str) -> None:
    with pytest.raises(ProviderConfigurationError) as exc_info:
        build_bearer_auth_headers(SecretStr(credential))

    rendered_error = f"{exc_info.value!s}\n{exc_info.value!r}"
    if credential:
        assert credential not in rendered_error


@pytest.mark.asyncio
async def test_http_exception_does_not_render_authorization_header() -> None:
    secret = "exception-safe-bearer-token"
    headers = build_bearer_auth_headers(SecretStr(secret))

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("transport unavailable", request=request)

    client = LLMHTTPClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(httpx.ConnectError) as exc_info:
            await client.request(
                "POST",
                "https://provider.example.test/v1/generate",
                headers=headers,
            )
    finally:
        await client.aclose()

    rendered_error = f"{exc_info.value!s}\n{exc_info.value!r}"
    assert secret not in rendered_error


@pytest.mark.asyncio
async def test_aclose_is_idempotent() -> None:
    class RecordingTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(lambda _: httpx.Response(200))
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1
            await super().aclose()

    transport = RecordingTransport()
    client = LLMHTTPClient(
        _settings(),
        transport=transport,
    )

    await client.aclose()
    await client.aclose()

    assert transport.close_calls == 1
    assert client.is_closed is True


def test_module_has_no_import_time_client_construction() -> None:
    tree = ast.parse(CLIENT_MODULE_PATH.read_text(encoding="utf-8"))
    top_level_calls = [
        node
        for statement in tree.body
        for node in ast.walk(statement)
        if not isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and isinstance(node, ast.Call)
    ]

    assert not any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "httpx"
        and call.func.attr == "AsyncClient"
        for call in top_level_calls
    )


def test_http_client_does_not_inherit_environment_proxy_configuration() -> None:
    tree = ast.parse(CLIENT_MODULE_PATH.read_text(encoding="utf-8"))
    constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx"
        and node.func.attr == "AsyncClient"
    ]

    assert len(constructors) == 1
    keyword_values = {
        keyword.arg: keyword.value
        for keyword in constructors[0].keywords
        if keyword.arg is not None
    }
    trust_env = keyword_values["trust_env"]
    assert isinstance(trust_env, ast.Constant)
    assert trust_env.value is False


def test_http_client_has_no_forbidden_architecture_dependencies() -> None:
    source = CLIENT_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
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
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.llm.providers",
        "openai",
        "deepseek",
    )

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden_prefixes
    )
    assert "api.openai.com" not in source
    assert "api.deepseek.com" not in source
