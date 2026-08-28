"""Shared offline guard and isolated PostgreSQL integration fixtures."""

import asyncio
import ipaddress
import os
import re
import socket
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"
DATABASE_NAME_PATTERN = re.compile(r"^home_ai_hub_test_[0-9a-f]{32}$")
_NETWORK_BLOCK_MESSAGE = "External network access is forbidden in default tests"
_LLM_COST_ACKNOWLEDGEMENT = "LLM_INTEGRATION_ACKNOWLEDGE_COST"
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYADDR = socket.gethostbyaddr
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex


type ProviderEnvironmentLoader = Callable[
    [str, tuple[str, ...]],
    Mapping[str, str],
]


def _llm_cost_is_acknowledged(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Accept only an explicit true value for billable integration tests."""

    source = os.environ if environment is None else environment
    return source.get(_LLM_COST_ACKNOWLEDGEMENT, "").strip().lower() == "true"


def _llm_integration_skip_reason(
    *,
    run_requested: bool,
    cost_acknowledged: bool,
) -> str | None:
    """Return the first unmet global LLM integration precondition."""

    if not run_requested:
        return "requires explicit --run-llm-integration"
    if not cost_acknowledged:
        return (
            "requires explicit cost acknowledgement: set "
            "LLM_INTEGRATION_ACKNOWLEDGE_COST=true"
        )
    return None


def _external_network_is_allowed(
    *,
    is_postgresql_integration: bool,
    run_postgresql_integration: bool,
    is_llm_integration: bool,
    run_llm_integration: bool,
    cost_acknowledged: bool,
) -> bool:
    """Allow network only for a fully enabled external-service test."""

    postgresql_allowed = (
        is_postgresql_integration and run_postgresql_integration
    )
    llm_allowed = (
        is_llm_integration
        and run_llm_integration
        and cost_acknowledged
    )
    return postgresql_allowed or llm_allowed


def _is_loopback_host(host: object) -> bool:
    """Return true only for an explicit localhost or loopback IP address."""

    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False

    normalized_host = host.strip().rstrip(".").lower()
    if normalized_host == "localhost":
        return True
    if not normalized_host:
        return False

    address_without_scope = normalized_host.split("%", maxsplit=1)[0]
    try:
        return ipaddress.ip_address(address_without_scope).is_loopback
    except ValueError:
        return False


def _connection_targets_loopback(address: object) -> bool:
    """Safely extract and classify the host from an INET socket address."""

    return (
        isinstance(address, tuple)
        and bool(address)
        and _is_loopback_host(address[0])
    )


def _block_external_network() -> NoReturn:
    """Raise a payload-free failure for a forbidden network operation."""

    raise AssertionError(_NETWORK_BLOCK_MESSAGE)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add independent switches for PostgreSQL and billable LLM tests."""

    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run PostgreSQL integration tests",
    )
    parser.addoption(
        "--run-llm-integration",
        action="store_true",
        default=False,
        help="run explicitly acknowledged real LLM provider integration tests",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip each external-service family unless its own gate is satisfied."""

    run_postgresql = bool(config.getoption("--run-integration"))
    run_llm = bool(config.getoption("--run-llm-integration"))
    llm_skip_reason = _llm_integration_skip_reason(
        run_requested=run_llm,
        cost_acknowledged=_llm_cost_is_acknowledged(),
    )

    skip_integration = pytest.mark.skip(
        reason="requires PostgreSQL; rerun with --run-integration",
    )
    for item in items:
        if "integration" in item.keywords and not run_postgresql:
            item.add_marker(skip_integration)
        if "llm_integration" in item.keywords and llm_skip_reason is not None:
            item.add_marker(pytest.mark.skip(reason=llm_skip_reason))


@pytest.fixture(autouse=True)
def block_external_network_by_default(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Fail immediately if a default test attempts DNS or socket access."""

    network_is_allowed = _external_network_is_allowed(
        is_postgresql_integration=(
            request.node.get_closest_marker("integration") is not None
        ),
        run_postgresql_integration=bool(
            request.config.getoption("--run-integration")
        ),
        is_llm_integration=(
            request.node.get_closest_marker("llm_integration") is not None
        ),
        run_llm_integration=bool(
            request.config.getoption("--run-llm-integration")
        ),
        cost_acknowledged=_llm_cost_is_acknowledged(),
    )
    if network_is_allowed:
        yield
        return

    def guarded_create_connection(
        address: object,
        *args: object,
        **kwargs: object,
    ) -> socket.socket:
        if not _connection_targets_loopback(address):
            _block_external_network()
        return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)

    def guarded_getaddrinfo(
        host: object,
        *args: object,
        **kwargs: object,
    ) -> list[tuple[object, ...]]:
        if not _is_loopback_host(host):
            _block_external_network()
        return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)

    def guarded_gethostbyaddr(host: object) -> tuple[str, list[str], list[str]]:
        if not _is_loopback_host(host):
            _block_external_network()
        return _ORIGINAL_GETHOSTBYADDR(host)

    def guarded_gethostbyname(host: object) -> str:
        if not _is_loopback_host(host):
            _block_external_network()
        return _ORIGINAL_GETHOSTBYNAME(host)

    def guarded_gethostbyname_ex(
        host: object,
    ) -> tuple[str, list[str], list[str]]:
        if not _is_loopback_host(host):
            _block_external_network()
        return _ORIGINAL_GETHOSTBYNAME_EX(host)

    def guarded_socket_connect(
        connected_socket: socket.socket,
        address: object,
    ) -> None:
        if not _connection_targets_loopback(address):
            _block_external_network()
        _ORIGINAL_SOCKET_CONNECT(connected_socket, address)

    def guarded_socket_connect_ex(
        connected_socket: socket.socket,
        address: object,
    ) -> int:
        if not _connection_targets_loopback(address):
            _block_external_network()
        return _ORIGINAL_SOCKET_CONNECT_EX(connected_socket, address)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)
    monkeypatch.setattr(socket, "gethostbyname", guarded_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    monkeypatch.setattr(socket.socket, "connect", guarded_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_socket_connect_ex)

    yield


@pytest.fixture
def require_llm_provider_environment() -> ProviderEnvironmentLoader:
    """Skip safely unless every named provider variable has a nonblank value."""

    def load(
        provider_display_name: str,
        variable_names: tuple[str, ...],
    ) -> Mapping[str, str]:
        missing = tuple(
            name
            for name in variable_names
            if not os.environ.get(name, "").strip()
        )
        if missing:
            pytest.skip(
                f"{provider_display_name} LLM integration requires: "
                + ", ".join(missing)
            )
        return {name: os.environ[name] for name in variable_names}

    return load


def _quoted_database_name(database_name: str) -> str:
    """Validate and quote the generated PostgreSQL database identifier."""

    if DATABASE_NAME_PATTERN.fullmatch(database_name) is None:
        raise ValueError("Unsafe test database name")
    return f'"{database_name}"'


async def _create_database(
    admin_url: URL,
    database_name: str,
    timeout_seconds: float,
) -> None:
    """Create one isolated database using an autocommit connection."""

    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        connect_args={"timeout": timeout_seconds},
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(f"CREATE DATABASE {_quoted_database_name(database_name)}")
            )
    finally:
        await engine.dispose()


async def _drop_database(
    admin_url: URL,
    database_name: str,
    timeout_seconds: float,
) -> None:
    """Drop the isolated database and terminate any remaining connections."""

    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        connect_args={"timeout": timeout_seconds},
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "DROP DATABASE IF EXISTS "
                    f"{_quoted_database_name(database_name)} WITH (FORCE)"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def integration_database_url() -> Iterator[str]:
    """Yield a unique PostgreSQL database URL and remove it after the suite."""

    settings = Settings()
    source_url = make_url(settings.database_url.get_secret_value())
    admin_url = source_url.set(database="postgres")
    database_name = f"home_ai_hub_test_{uuid4().hex}"
    test_url = source_url.set(database=database_name)
    timeout_seconds = settings.database_healthcheck_timeout_seconds

    asyncio.run(_create_database(admin_url, database_name, timeout_seconds))
    try:
        yield test_url.render_as_string(hide_password=False)
    finally:
        asyncio.run(_drop_database(admin_url, database_name, timeout_seconds))


@pytest.fixture(scope="session")
def migrated_database_url(integration_database_url: str) -> str:
    """Apply every Alembic migration to the isolated test database."""

    alembic_config = Config(str(ALEMBIC_CONFIG_PATH))
    alembic_config.attributes["database_url"] = integration_database_url
    command.upgrade(alembic_config, "head")
    return integration_database_url


@pytest.fixture(scope="session")
def alembic_head_revision() -> str:
    """Return the single migration head declared by the project."""

    alembic_config = Config(str(ALEMBIC_CONFIG_PATH))
    revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic has no head revision")
    return revision
