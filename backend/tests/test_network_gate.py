"""Regression tests for the default loopback-aware network gate."""

from __future__ import annotations

import ipaddress
import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import conftest as suite_config


_BLOCK_MESSAGE = "External network access is forbidden in default tests"


@pytest.mark.parametrize(
    "host",
    (
        "localhost",
        "localhost.",
        "127.0.0.1",
        "127.42.7.9",
        "127.255.255.254",
        "::1",
        "::1%0",
    ),
)
def test_loopback_classifier_accepts_only_explicit_loopback_hosts(
    host: str,
) -> None:
    assert suite_config._is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    (
        "8.8.8.8",
        "1.1.1.1",
        "0.0.0.0",
        "::",
        "api.openai.com",
        "api.deepseek.com",
        "provider.example.test",
        "localhost.example.test",
        "",
    ),
)
def test_loopback_classifier_rejects_external_or_ambiguous_hosts(
    host: str,
) -> None:
    assert suite_config._is_loopback_host(host) is False


def test_default_gate_blocks_public_socket_connect_without_network_io() -> None:
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError, match=_BLOCK_MESSAGE) as exc_info:
            client_socket.connect(("8.8.8.8", 53))
    finally:
        client_socket.close()

    assert str(exc_info.value) == _BLOCK_MESSAGE


@pytest.mark.parametrize(
    "host",
    ("api.openai.com", "api.deepseek.com", "provider.example.test"),
)
def test_default_gate_blocks_supplier_and_test_domains(host: str) -> None:
    with pytest.raises(AssertionError, match=_BLOCK_MESSAGE):
        socket.getaddrinfo(host, 443)
    with pytest.raises(AssertionError, match=_BLOCK_MESSAGE):
        socket.create_connection((host, 443), timeout=0.01)


def test_localhost_dns_resolution_remains_available() -> None:
    resolved = socket.getaddrinfo(
        "localhost",
        0,
        type=socket.SOCK_STREAM,
    )
    resolved_addresses = {
        result[4][0].split("%", maxsplit=1)[0]
        for result in resolved
    }

    assert resolved_addresses
    assert all(
        ipaddress.ip_address(address).is_loopback
        for address in resolved_addresses
    )


def test_loopback_socket_connect_remains_available() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    accepted: socket.socket | None = None
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.connect(server.getsockname())
        accepted, _ = server.accept()
        client.sendall(b"ok")
        assert accepted.recv(2) == b"ok"
    finally:
        if accepted is not None:
            accepted.close()
        client.close()
        server.close()


def test_standard_library_socketpair_remains_available() -> None:
    first, second = socket.socketpair()
    try:
        first.sendall(b"ok")
        assert second.recv(2) == b"ok"
    finally:
        first.close()
        second.close()


def test_fastapi_testclient_can_start_with_default_network_gate() -> None:
    application = FastAPI()

    @application.get("/local-test")
    async def local_test() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(application) as client:
        response = client.get("/local-test")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

