"""Offline success and validation contracts for Conversation HTTP endpoints."""

from fastapi.testclient import TestClient

from app.application.conversations import (
    ArchiveConversationCommand,
    ConversationChatCommand,
    CreateConversationCommand,
)
from tests.conversations.support import (
    CONVERSATION_ID,
    build_test_application,
)


BASE_ENDPOINT = "/api/v1/conversations"


def test_create_conversation_returns_public_resource() -> None:
    application, command_service, _, _ = build_test_application()

    with TestClient(application) as client:
        response = client.post(BASE_ENDPOINT, json={"title": "Offline conversation"})

    assert response.status_code == 201
    assert response.json() == {
        "id": str(CONVERSATION_ID),
        "title": "Offline conversation",
        "status": "active",
        "created_at": "2026-09-01T14:00:00Z",
        "updated_at": "2026-09-01T14:00:00Z",
        "archived_at": None,
    }
    command_service.create_conversation.assert_awaited_once_with(
        CreateConversationCommand(title="Offline conversation")
    )


def test_create_rejects_long_title_and_unknown_configuration_fields() -> None:
    application, command_service, _, _ = build_test_application()

    with TestClient(application) as client:
        long_title = client.post(BASE_ENDPOINT, json={"title": "x" * 201})
        provider_config = client.post(
            BASE_ENDPOINT,
            json={"title": "safe", "provider": "openai"},
        )

    assert long_title.status_code == 422
    assert provider_config.status_code == 422
    assert long_title.json()["error"]["code"] == "validation_error"
    assert provider_config.json()["error"]["code"] == "validation_error"
    command_service.create_conversation.assert_not_awaited()


def test_list_and_get_conversations_use_offset_limit_pagination() -> None:
    application, _, query_service, _ = build_test_application()

    with TestClient(application) as client:
        listing = client.get(f"{BASE_ENDPOINT}?offset=0&limit=50")
        detail = client.get(f"{BASE_ENDPOINT}/{CONVERSATION_ID}")

    assert listing.status_code == 200
    assert listing.json()["offset"] == 0
    assert listing.json()["limit"] == 50
    assert listing.json()["next_offset"] is None
    assert listing.json()["items"][0]["id"] == str(CONVERSATION_ID)
    assert detail.status_code == 200
    assert detail.json()["id"] == str(CONVERSATION_ID)
    query_service.list_conversations.assert_awaited_once_with(offset=0, limit=50)
    query_service.get_conversation.assert_awaited_once_with(CONVERSATION_ID)


def test_list_messages_returns_cursor_metadata_and_public_dtos() -> None:
    application, _, query_service, _ = build_test_application()

    with TestClient(application) as client:
        response = client.get(
            f"{BASE_ENDPOINT}/{CONVERSATION_ID}/messages?limit=100"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["after_sequence"] is None
    assert body["limit"] == 100
    assert body["next_cursor"] == 2
    assert [item["role"] for item in body["items"]] == ["user", "assistant"]
    assert [item["sequence"] for item in body["items"]] == [1, 2]
    query_service.list_messages.assert_awaited_once_with(
        CONVERSATION_ID,
        after_sequence=None,
        limit=100,
    )


def test_create_turn_is_non_streaming_and_returns_normalized_messages() -> None:
    application, _, _, chat_service = build_test_application()

    with TestClient(application) as client:
        response = client.post(
            f"{BASE_ENDPOINT}/{CONVERSATION_ID}/turns",
            json={
                "content": "Offline question",
                "idempotency_key": "turn-key-001",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == str(CONVERSATION_ID)
    assert body["turn_id"]
    assert body["user_message"]["content"] == "Offline question"
    assert body["assistant_message"]["content"] == "Offline answer"
    assert body["provider_name"] == "mock"
    assert body["model_name"] == "mock-default"
    assert body["finish_reason"] == "stop"
    assert body["usage"] == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }
    assert body["request_id"] == "request-001"
    assert body["status"] == "completed"
    assert "answer" not in body
    assert "provider_request_id" not in response.text
    chat_service.complete.assert_awaited_once_with(
        ConversationChatCommand(
            conversation_id=CONVERSATION_ID,
            user_content="Offline question",
            idempotency_key="turn-key-001",
        )
    )


def test_create_turn_rejects_empty_streaming_and_provider_override_inputs() -> None:
    application, _, _, chat_service = build_test_application()
    endpoint = f"{BASE_ENDPOINT}/{CONVERSATION_ID}/turns"

    with TestClient(application) as client:
        empty = client.post(endpoint, json={"content": "   "})
        streaming = client.post(
            endpoint,
            json={"content": "safe", "stream": True},
        )
        provider = client.post(
            endpoint,
            json={"content": "safe", "provider_name": "deepseek"},
        )

    assert empty.status_code == 422
    assert streaming.status_code == 422
    assert provider.status_code == 422
    chat_service.complete.assert_not_awaited()


def test_archive_is_idempotent_at_the_http_application_boundary() -> None:
    application, command_service, _, _ = build_test_application()
    endpoint = f"{BASE_ENDPOINT}/{CONVERSATION_ID}/archive"

    with TestClient(application) as client:
        first = client.post(endpoint)
        second = client.post(endpoint)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "archived"
    assert first.json()["conversation"]["status"] == "archived"
    assert command_service.archive_conversation.await_count == 2
    assert command_service.archive_conversation.await_args_list[0].args == (
        ArchiveConversationCommand(CONVERSATION_ID),
    )
