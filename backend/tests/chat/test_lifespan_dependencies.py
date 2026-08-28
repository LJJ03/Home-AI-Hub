"""Lifecycle and dependency tests for the Chat application boundary."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.dependencies.chat import get_chat_service
from app.core.config import Settings
from app.llm import ProviderNotRegistered
from app.llm.bootstrap import bootstrap_llm
from app.llm.config import LLMSettings
from app.llm.http.client import LLMHTTPClient
from app.llm.service import LLMService
from app.main import create_app
from app.services import ChatService


DEPENDENCY_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "app/api/dependencies/chat.py"
)


def _app_settings() -> Settings:
    return Settings(
        _env_file=None,
        name="Home AI Hub Test API",
        version="5.0.0-test",
        environment="test",
        host="127.0.0.1",
        port=8000,
        log_level="CRITICAL",
        database_url="postgresql+asyncpg://test:test@127.0.0.1:5432/test",
        sqlalchemy_echo=False,
        pool_size=1,
        max_overflow=0,
        database_healthcheck_timeout_seconds=1,
    )


def _llm_settings(provider: str = "mock") -> LLMSettings:
    values: dict[str, object] = {
        "provider": provider,
        "default_model": "lifespan-mock-model",
        "timeout_seconds": 30,
        "default_temperature": 0.7,
        "default_max_tokens": 1024,
    }
    if provider in {"deepseek", "openai"}:
        values.update(
            {
                f"{provider}_api_key": f"{provider}-test-secret",
                f"{provider}_base_url": f"https://{provider}.example.test/v1",
                f"{provider}_default_model": f"{provider}-test-model",
            }
        )

    return LLMSettings(
        _env_file=None,
        **values,
    )


class _RecordingDatabaseManager:
    """Record lifecycle calls without creating an engine or connection."""

    instances: list["_RecordingDatabaseManager"] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.start_calls = 0
        self.stop_calls = 0
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


def _request_for(application: FastAPI) -> Request:
    return Request({"type": "http", "app": application})


def test_mock_provider_configuration_starts_and_stops_application() -> None:
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )

    with TestClient(application):
        llm_service = application.state.llm_service
        assert isinstance(llm_service, LLMService)
        assert llm_service.diagnose().provider_name == "mock"
        assert llm_service.diagnose().default_model == "lifespan-mock-model"

    assert not hasattr(application.state, "llm_service")
    assert not hasattr(application.state, "database_manager")


def test_application_shutdown_closes_lifespan_owned_llm_service() -> None:
    llm_service = Mock(spec=LLMService)
    llm_service.aclose = AsyncMock()
    llm_settings = _llm_settings()
    application = create_app(_app_settings(), llm_settings=llm_settings)

    with patch("app.main.bootstrap_llm", return_value=llm_service) as bootstrap:
        with TestClient(application):
            assert application.state.llm_service is llm_service

    bootstrap.assert_called_once_with(llm_settings)
    llm_service.aclose.assert_awaited_once_with()
    assert not hasattr(application.state, "llm_service")


def test_application_instances_do_not_share_llm_service_state() -> None:
    first_application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )
    second_application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )

    with TestClient(first_application), TestClient(second_application):
        assert (
            first_application.state.llm_service
            is not second_application.state.llm_service
        )


def test_chat_dependency_uses_state_without_bootstrap_or_environment_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )

    with patch("app.main.bootstrap_llm", wraps=bootstrap_llm) as bootstrap:
        with TestClient(application):
            monkeypatch.setenv("LLM_PROVIDER", "deepseek")
            first = get_chat_service(_request_for(application))
            second = get_chat_service(_request_for(application))

            assert isinstance(first, ChatService)
            assert isinstance(second, ChatService)
            assert first is not second
            assert first._llm_service is application.state.llm_service
            assert second._llm_service is application.state.llm_service
            assert bootstrap.call_count == 1


def test_chat_dependency_fails_when_lifespan_resource_is_missing() -> None:
    application = FastAPI()

    with pytest.raises(RuntimeError, match="LLM service is not initialized"):
        get_chat_service(_request_for(application))


def test_unknown_provider_fails_startup_and_releases_database() -> None:
    provider_name = "unknown-provider"
    _RecordingDatabaseManager.instances.clear()
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(provider_name),
    )

    with patch("app.main.DatabaseManager", _RecordingDatabaseManager):
        with pytest.raises(ProviderNotRegistered) as raised:
            with TestClient(application):
                pass

    manager = _RecordingDatabaseManager.instances[-1]
    assert raised.value.provider_name == provider_name
    assert manager.start_calls == 1
    assert manager.stop_calls == 1
    assert not hasattr(application.state, "database_manager")
    assert not hasattr(application.state, "llm_service")


@pytest.mark.parametrize("provider_name", ("deepseek", "openai"))
def test_registered_real_provider_starts_without_remote_probe(
    provider_name: str,
) -> None:
    _RecordingDatabaseManager.instances.clear()
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(provider_name),
    )

    with (
        patch("app.main.DatabaseManager", _RecordingDatabaseManager),
        patch.object(
            LLMHTTPClient,
            "request",
            new_callable=AsyncMock,
        ) as request,
        patch.object(LLMHTTPClient, "stream") as stream,
    ):
        with TestClient(application):
            diagnostics = application.state.llm_service.diagnose()
            assert diagnostics.provider_name == provider_name
            request.assert_not_awaited()
            stream.assert_not_called()

    manager = _RecordingDatabaseManager.instances[-1]
    assert manager.start_calls == 1
    assert manager.stop_calls == 1
    assert not hasattr(application.state, "database_manager")
    assert not hasattr(application.state, "llm_service")


def test_database_still_stops_if_llm_shutdown_fails() -> None:
    _RecordingDatabaseManager.instances.clear()
    llm_service = Mock(spec=LLMService)
    llm_service.aclose = AsyncMock(side_effect=RuntimeError("LLM close failed"))
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )

    with (
        patch("app.main.DatabaseManager", _RecordingDatabaseManager),
        patch("app.main.bootstrap_llm", return_value=llm_service),
        pytest.raises(RuntimeError, match="LLM close failed"),
    ):
        with TestClient(application):
            pass

    manager = _RecordingDatabaseManager.instances[-1]
    assert manager.start_calls == 1
    assert manager.stop_calls == 1
    assert not hasattr(application.state, "database_manager")
    assert not hasattr(application.state, "llm_service")


def test_system_endpoints_remain_independent_from_llm_readiness() -> None:
    llm_service = Mock(spec=LLMService)
    llm_service.generate = AsyncMock(side_effect=AssertionError("Unexpected LLM call"))
    llm_service.aclose = AsyncMock()
    application = create_app(
        _app_settings(),
        llm_settings=_llm_settings(),
    )

    with patch("app.main.bootstrap_llm", return_value=llm_service):
        with TestClient(application) as client:
            with patch.object(
                application.state.database_manager,
                "check_connection",
                new_callable=AsyncMock,
            ) as check_connection:
                health_response = client.get("/health")
                ready_response = client.get("/ready")
                version_response = client.get("/version")

            assert health_response.status_code == 200
            assert health_response.json() == {"status": "ok"}
            assert ready_response.status_code == 200
            assert ready_response.json() == {"status": "ready"}
            assert version_response.status_code == 200
            assert version_response.json() == {"version": "0.1.0"}
            check_connection.assert_awaited_once_with()
            llm_service.generate.assert_not_awaited()
            llm_service.diagnose.assert_not_called()

    llm_service.aclose.assert_awaited_once_with()


def test_chat_dependency_module_has_no_composition_or_configuration_access() -> None:
    syntax_tree = ast.parse(DEPENDENCY_MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "app.llm.bootstrap",
        "app.llm.config",
        "app.llm.factory",
        "app.llm.registry",
        "app.llm.providers",
        "app.core.config",
        "pydantic_settings",
        "os",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
    )

    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    )
