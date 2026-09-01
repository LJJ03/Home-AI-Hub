"""PostgreSQL-backed integration contract for production Conversation wiring."""

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.llm.config import LLMSettings
from app.main import create_app


def _application_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        name="Home AI Hub Conversation Integration",
        version="8.0.0-test",
        environment="test",
        host="127.0.0.1",
        port=8000,
        log_level="CRITICAL",
        database_url=database_url,
        sqlalchemy_echo=False,
        pool_size=2,
        max_overflow=0,
        database_healthcheck_timeout_seconds=3,
    )


def _offline_llm_settings() -> LLMSettings:
    return LLMSettings(
        _env_file=None,
        provider="mock",
        default_model="conversation-integration-mock",
        timeout_seconds=30,
        default_temperature=0.7,
        default_max_tokens=256,
    )


@pytest.mark.integration
def test_conversation_api_uses_production_wiring_with_postgresql(
    migrated_database_url: str,
) -> None:
    """Exercise API, services, UoW, repositories, and migrated schema offline."""

    application = create_app(
        _application_settings(migrated_database_url),
        llm_settings=_offline_llm_settings(),
    )

    with TestClient(application) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "PostgreSQL integration conversation"},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        completed = client.post(
            f"/api/v1/conversations/{conversation_id}/turns",
            json={
                "content": "Persist this offline turn",
                "idempotency_key": "postgres-api-turn-001",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["provider_name"] == "mock"
        assert completed.json()["model_name"] == "conversation-integration-mock"
        assert completed.json()["status"] == "completed"

        messages = client.get(
            f"/api/v1/conversations/{conversation_id}/messages?limit=10"
        )
        assert messages.status_code == 200
        assert [item["role"] for item in messages.json()["items"]] == [
            "user",
            "assistant",
        ]
        assert [item["sequence"] for item in messages.json()["items"]] == [1, 2]

        archived = client.post(
            f"/api/v1/conversations/{conversation_id}/archive"
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        rejected = client.post(
            f"/api/v1/conversations/{conversation_id}/turns",
            json={
                "content": "Archived conversations reject new turns",
                "idempotency_key": "postgres-api-turn-002",
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"] == {
            "code": "conversation_archived",
            "message": "Conversation is archived",
        }
