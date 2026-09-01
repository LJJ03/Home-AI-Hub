"""Offline architecture and transaction tests for SQLAlchemy adapters."""

import ast
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.application.conversations import (
    ConversationRepository,
    ConversationTurnRepository,
    ConversationUnitOfWork,
    MessageRepository,
)
from app.repositories.conversations import (
    SqlAlchemyConversationRepository,
    SqlAlchemyConversationTurnRepository,
    SqlAlchemyMessageRepository,
)
from app.repositories.unit_of_work import SqlAlchemyConversationUnitOfWork


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = BACKEND_ROOT / "app" / "application" / "conversations"
DOMAIN_ROOT = BACKEND_ROOT / "app" / "domain" / "conversations"
ADAPTER_PATHS = (
    BACKEND_ROOT / "app" / "repositories" / "conversations.py",
    BACKEND_ROOT / "app" / "repositories" / "conversation_mappers.py",
    BACKEND_ROOT / "app" / "repositories" / "unit_of_work.py",
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_concrete_adapters_satisfy_application_protocols() -> None:
    session = FakeSession()

    assert isinstance(SqlAlchemyConversationRepository(session), ConversationRepository)
    assert isinstance(
        SqlAlchemyConversationTurnRepository(session),
        ConversationTurnRepository,
    )
    assert isinstance(SqlAlchemyMessageRepository(session), MessageRepository)


@pytest.mark.asyncio
async def test_sqlalchemy_unit_of_work_is_the_only_commit_boundary() -> None:
    session = FakeSession()

    @asynccontextmanager
    async def session_context():
        yield session

    unit_of_work = SqlAlchemyConversationUnitOfWork(session_context)
    assert isinstance(unit_of_work, ConversationUnitOfWork)
    async with unit_of_work:
        await unit_of_work.commit()

    assert session.commit_calls == 1
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_uncommitted_or_failed_unit_of_work_rolls_back() -> None:
    normal_session = FakeSession()

    @asynccontextmanager
    async def normal_context():
        yield normal_session

    async with SqlAlchemyConversationUnitOfWork(normal_context):
        pass
    assert normal_session.rollback_calls == 1

    failed_session = FakeSession()

    @asynccontextmanager
    async def failed_context():
        yield failed_session

    with pytest.raises(RuntimeError, match="expected failure"):
        async with SqlAlchemyConversationUnitOfWork(failed_context):
            raise RuntimeError("expected failure")
    assert failed_session.rollback_calls == 1


def test_protocols_are_sqlalchemy_and_fastapi_free() -> None:
    for path in APPLICATION_ROOT.glob("*.py"):
        imported = _imports(path)
        assert not any(
            module.startswith(("sqlalchemy", "fastapi", "starlette", "app.models"))
            for module in imported
        )


def test_domain_does_not_reverse_depend_on_persistence_or_application() -> None:
    for path in DOMAIN_ROOT.glob("*.py"):
        imported = _imports(path)
        assert not any(
            module.startswith(
                ("sqlalchemy", "app.application", "app.models", "app.repositories")
            )
            for module in imported
        )


def test_adapter_imports_have_no_connection_or_upper_layer_side_effects() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in ADAPTER_PATHS)
    imported = set().union(*(_imports(path) for path in ADAPTER_PATHS))

    assert "create_async_engine" not in source
    assert "create_all" not in source
    assert "alembic" not in source.lower()
    assert "os.environ" not in source
    assert "getenv(" not in source
    assert ".commit(" not in ADAPTER_PATHS[0].read_text(encoding="utf-8")
    assert not any(
        module.startswith(
            (
                "fastapi",
                "redis",
                "httpx",
                "app.api",
                "app.llm",
                "app.services",
            )
        )
        for module in imported
    )
