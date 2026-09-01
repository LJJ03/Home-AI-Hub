"""SQLAlchemy transaction adapter for the conversation unit of work."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.conversations import (
    SqlAlchemyConversationRepository,
    SqlAlchemyConversationTurnRepository,
    SqlAlchemyMessageRepository,
)


type AsyncSessionContextFactory = Callable[
    [],
    AbstractAsyncContextManager[AsyncSession],
]


class SqlAlchemyConversationUnitOfWork:
    """Own one injected AsyncSession context and its commit boundary."""

    def __init__(self, session_context_factory: AsyncSessionContextFactory) -> None:
        self._session_context_factory = session_context_factory
        self._session_context: AbstractAsyncContextManager[AsyncSession] | None = None
        self._session: AsyncSession | None = None
        self._conversation_repository: SqlAlchemyConversationRepository | None = None
        self._turn_repository: SqlAlchemyConversationTurnRepository | None = None
        self._message_repository: SqlAlchemyMessageRepository | None = None
        self._finished = False

    @property
    def conversation_repository(self) -> SqlAlchemyConversationRepository:
        if self._conversation_repository is None:
            raise RuntimeError("Unit of work has not been entered")
        return self._conversation_repository

    @property
    def turn_repository(self) -> SqlAlchemyConversationTurnRepository:
        if self._turn_repository is None:
            raise RuntimeError("Unit of work has not been entered")
        return self._turn_repository

    @property
    def message_repository(self) -> SqlAlchemyMessageRepository:
        if self._message_repository is None:
            raise RuntimeError("Unit of work has not been entered")
        return self._message_repository

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of work is already active")
        session_context = self._session_context_factory()
        session = await session_context.__aenter__()
        self._session_context = session_context
        self._session = session
        self._conversation_repository = SqlAlchemyConversationRepository(session)
        self._turn_repository = SqlAlchemyConversationTurnRepository(session)
        self._message_repository = SqlAlchemyMessageRepository(session)
        self._finished = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session_context = self._session_context
        try:
            if self._session is not None and (exc_type is not None or not self._finished):
                await self.rollback()
        finally:
            self._conversation_repository = None
            self._turn_repository = None
            self._message_repository = None
            self._session = None
            self._session_context = None
            self._finished = False
            if session_context is not None:
                await session_context.__aexit__(exc_type, exc_value, traceback)

    async def commit(self) -> None:
        session = self._require_active_session()
        if self._finished:
            raise RuntimeError("Unit of work transaction is already finished")
        await session.commit()
        self._finished = True

    async def rollback(self) -> None:
        session = self._require_active_session()
        if not self._finished:
            await session.rollback()
        self._finished = True

    def _require_active_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered")
        return self._session
