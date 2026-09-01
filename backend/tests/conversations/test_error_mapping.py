"""Safe Conversation API error mapping tests."""

from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient

from app.application.conversations import (
    ConversationApplicationError,
    ConversationConflictError,
    ConversationGenerationError,
    ConversationNotFoundError,
    ConversationPersistenceUnavailableError,
)
from tests.conversations.support import CONVERSATION_ID, build_test_application


BASE_ENDPOINT = "/api/v1/conversations"
SENSITIVE_VALUES = (
    "sk-sensitive-api-key-value",
    "Bearer sensitive-authorization-value",
    "raw provider response body",
    "postgresql://private-user:private-password@private-host/database",
)


def test_missing_conversation_maps_to_404() -> None:
    application, _, query_service, _ = build_test_application()
    query_service.get_conversation = AsyncMock(
        side_effect=ConversationNotFoundError(CONVERSATION_ID)
    )

    with TestClient(application) as client:
        response = client.get(f"{BASE_ENDPOINT}/{CONVERSATION_ID}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "conversation_not_found",
            "message": "Conversation was not found",
        }
    }


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    (
        (
            ConversationConflictError(
                code="conversation_archived",
                message=SENSITIVE_VALUES[2],
            ),
            "conversation_archived",
        ),
        (
            ConversationConflictError(
                code="idempotency_conflict",
                message=SENSITIVE_VALUES[2],
            ),
            "idempotency_conflict",
        ),
    ),
)
def test_write_conflicts_map_to_safe_409(
    exception: ConversationConflictError,
    expected_code: str,
) -> None:
    application, _, _, chat_service = build_test_application()
    chat_service.complete = AsyncMock(side_effect=exception)

    with TestClient(application) as client:
        response = client.post(
            f"{BASE_ENDPOINT}/{CONVERSATION_ID}/turns",
            json={"content": "safe input"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in response.text


def test_persistence_unavailable_maps_to_503() -> None:
    application, _, query_service, _ = build_test_application()
    query_service.list_conversations = AsyncMock(
        side_effect=ConversationPersistenceUnavailableError()
    )

    with TestClient(application) as client:
        response = client.get(BASE_ENDPOINT)

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "conversation_persistence_unavailable",
            "message": "Conversation persistence is temporarily unavailable",
        }
    }


def test_llm_failure_reuses_safe_provider_error_semantics() -> None:
    application, _, _, chat_service = build_test_application()
    exception = ConversationGenerationError(code="provider_timeout")
    exception.__cause__ = RuntimeError(" | ".join(SENSITIVE_VALUES))
    chat_service.complete = AsyncMock(side_effect=exception)

    with TestClient(application) as client:
        response = client.post(
            f"{BASE_ENDPOINT}/{CONVERSATION_ID}/turns",
            json={"content": "safe input"},
        )

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "code": "llm_provider_timeout",
            "message": "LLM provider timed out",
        }
    }
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in response.text


def test_unknown_application_error_maps_to_safe_500() -> None:
    application, command_service, _, _ = build_test_application()
    exception = ConversationApplicationError(" | ".join(SENSITIVE_VALUES))
    command_service.create_conversation = AsyncMock(side_effect=exception)

    with TestClient(application) as client:
        response = client.post(BASE_ENDPOINT, json={})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "conversation_application_error",
            "message": "Conversation operation failed",
        }
    }
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in response.text


def test_unknown_non_application_error_uses_existing_safe_500_handler() -> None:
    application, command_service, _, _ = build_test_application()
    command_service.create_conversation = AsyncMock(
        side_effect=RuntimeError(" | ".join(SENSITIVE_VALUES))
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(BASE_ENDPOINT, json={})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred",
        }
    }
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in response.text
