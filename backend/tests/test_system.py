"""Basic contract tests for infrastructure endpoints."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import DatabaseUnavailableError
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run application lifespan events around each test."""

    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready(client: TestClient) -> None:
    with patch.object(
        client.app.state.database_manager,
        "check_connection",
        new_callable=AsyncMock,
    ) as check_connection:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    check_connection.assert_awaited_once_with()


def test_ready_returns_503_when_database_is_unavailable(
    client: TestClient,
) -> None:
    with patch.object(
        client.app.state.database_manager,
        "check_connection",
        new_callable=AsyncMock,
        side_effect=DatabaseUnavailableError("Database connectivity check failed"),
    ) as check_connection:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "Database is unavailable",
        }
    }
    check_connection.assert_awaited_once_with()


def test_version(client: TestClient) -> None:
    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": "0.1.0"}


def test_unknown_route_uses_unified_error_shape(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "http_error", "message": "Not Found"}
    }
