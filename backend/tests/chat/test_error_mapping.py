"""Security and HTTP contract tests for centralized LLM error mapping."""

import ast
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.chat import get_chat_service
from app.api.dependencies.database import get_database_manager
from app.api.router import api_router
from app.core.exceptions import register_exception_handlers
from app.db.session import DatabaseUnavailableError
from app.llm import (
    LLMException,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidResponse,
    ProviderNotRegistered,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.services import ChatService


ERROR_MAPPING_PATH = (
    Path(__file__).resolve().parents[2] / "app/api/error_mapping/llm.py"
)
CHAT_ENDPOINT = "/api/v1/chat/completions"
REQUEST_ID = "safe-request-001"
SENSITIVE_VALUES = (
    "sk-sensitive-api-key",
    "Full confidential prompt",
    "Full confidential model response",
    "VendorSDKException",
    "provider-request-secret",
)


def _chat_payload() -> dict[str, object]:
    return {
        "messages": [{"role": "user", "content": "Safe test input"}],
        "request_id": REQUEST_ID,
    }


def _test_application(chat_service: object) -> tuple[FastAPI, AsyncMock]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    database_check = AsyncMock()
    database_manager = Mock()
    database_manager.check_connection = database_check
    application.dependency_overrides[get_chat_service] = lambda: chat_service
    application.dependency_overrides[get_database_manager] = lambda: database_manager
    return application, database_check


def _sensitive_message() -> str:
    return " | ".join(SENSITIVE_VALUES[:3])


def _attach_sensitive_cause(exception: LLMException) -> LLMException:
    exception.__cause__ = RuntimeError(SENSITIVE_VALUES[3])
    return exception


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code", "expected_message"),
    (
        (
            ProviderConfigurationError(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            500,
            "llm_configuration_error",
            "LLM provider configuration is invalid",
        ),
        (
            ProviderNotRegistered(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            500,
            "llm_provider_not_registered",
            "Configured LLM provider is not registered",
        ),
        (
            ProviderAuthenticationError(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            502,
            "llm_provider_authentication_failed",
            "LLM provider authentication failed",
        ),
        (
            ProviderRateLimitError(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
                retry_after_seconds=2.5,
            ),
            429,
            "llm_rate_limited",
            "LLM request was rate limited",
        ),
        (
            ProviderTimeout(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            504,
            "llm_provider_timeout",
            "LLM provider timed out",
        ),
        (
            ProviderUnavailable(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            503,
            "llm_provider_unavailable",
            "LLM provider is unavailable",
        ),
        (
            ProviderInvalidResponse(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            502,
            "llm_invalid_response",
            "LLM provider returned an invalid response",
        ),
        (
            LLMException(
                _sensitive_message(),
                provider_name="vendor-secret",
                provider_request_id=SENSITIVE_VALUES[4],
            ),
            502,
            "llm_provider_error",
            "LLM provider request failed",
        ),
    ),
    ids=(
        "configuration",
        "not-registered",
        "authentication",
        "rate-limit",
        "timeout",
        "unavailable",
        "invalid-response",
        "generic",
    ),
)
def test_llm_exception_maps_to_safe_http_error(
    exception: LLMException,
    expected_status: int,
    expected_code: str,
    expected_message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _attach_sensitive_cause(exception)
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(side_effect=exception)
    application, _ = _test_application(chat_service)

    with caplog.at_level(logging.WARNING):
        with TestClient(application) as client:
            response = client.post(CHAT_ENDPOINT, json=_chat_payload())

    assert response.status_code == expected_status
    expected_details: dict[str, str | float] = {"request_id": REQUEST_ID}
    if isinstance(exception, ProviderRateLimitError):
        expected_details["retry_after_seconds"] = 2.5
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": expected_message,
            "details": expected_details,
        }
    }
    serialized_response = response.text
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in serialized_response
        assert sensitive_value not in caplog.text
    assert "provider_request_id" not in serialized_response
    assert "provider_name" not in response.json()["error"]
    chat_service.complete.assert_awaited_once()


def test_non_finite_retry_after_is_not_exposed() -> None:
    exception = ProviderRateLimitError(
        _sensitive_message(),
        retry_after_seconds=float("nan"),
    )
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(side_effect=exception)
    application, _ = _test_application(chat_service)

    with TestClient(application) as client:
        response = client.post(CHAT_ENDPOINT, json=_chat_payload())

    assert response.status_code == 429
    assert response.json()["error"]["details"] == {"request_id": REQUEST_ID}


def test_request_validation_keeps_existing_422_error_contract() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock()
    application, _ = _test_application(chat_service)

    with TestClient(application) as client:
        response = client.post(CHAT_ENDPOINT, json={"messages": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"] == "Request validation failed"
    chat_service.complete.assert_not_awaited()


def test_unknown_exception_uses_existing_safe_500_handler() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(
        side_effect=RuntimeError("Unexpected private implementation failure")
    )
    application, _ = _test_application(chat_service)

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(CHAT_ENDPOINT, json=_chat_payload())

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred",
        }
    }
    assert "private implementation failure" not in response.text
    chat_service.complete.assert_awaited_once()


def test_system_endpoint_error_semantics_are_unchanged() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock()
    application, database_check = _test_application(chat_service)
    database_check.side_effect = DatabaseUnavailableError(
        "Database connectivity check failed"
    )

    with TestClient(application) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")
        version_response = client.get("/version")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert ready_response.status_code == 503
    assert ready_response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "Database is unavailable",
        }
    }
    assert version_response.status_code == 200
    assert version_response.json() == {"version": "0.1.0"}
    database_check.assert_awaited_once_with()
    chat_service.complete.assert_not_awaited()


def test_llm_error_mapping_module_respects_adapter_boundaries() -> None:
    syntax_tree = ast.parse(ERROR_MAPPING_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "app.llm.service",
        "app.llm.providers",
        "app.llm.registry",
        "app.llm.factory",
        "app.llm.bootstrap",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
        "pydantic_settings",
        "os",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
    )

    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    )
