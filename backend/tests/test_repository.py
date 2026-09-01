"""Generic async repository integration tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.conversations import Conversation, ConversationStatus, TokenUsage
from app.models.conversations import ConversationModel
from app.models.system_info import SystemInfo
from app.repositories.base import BaseRepository
from app.repositories.unit_of_work import SqlAlchemyConversationUnitOfWork


async def _verify_row_lock(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: UUID,
) -> None:
    first = SqlAlchemyConversationUnitOfWork(session_factory)
    await first.__aenter__()
    task: asyncio.Task[Conversation | None] | None = None
    try:
        locked = await first.conversation_repository.get_for_update(conversation_id)
        assert locked is not None
        second_started = asyncio.Event()

        async def acquire_from_second_transaction() -> Conversation | None:
            async with SqlAlchemyConversationUnitOfWork(session_factory) as second:
                second_started.set()
                result = await second.conversation_repository.get_for_update(
                    conversation_id
                )
                await second.rollback()
                return result

        task = asyncio.create_task(acquire_from_second_transaction())
        await second_started.wait()
        await asyncio.sleep(0.1)
        assert not task.done()
        await first.commit()
    finally:
        await first.__aexit__(None, None, None)

    assert task is not None
    second_result = await asyncio.wait_for(task, timeout=2)
    assert isinstance(second_result, Conversation)


async def _verify_conversation_repositories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    conversation = Conversation.create(
        title="Repository integration",
        created_at=now,
    )
    first_turn = conversation.start_turn(
        user_content="integration user message",
        request_id="shared-request-id",
        idempotency_key="idempotency-one",
        created_at=now + timedelta(seconds=1),
    )
    conversation.complete_turn(
        first_turn.id,
        assistant_content="integration assistant message",
        provider_name="mock",
        model_name="mock-default",
        finish_reason="stop",
        usage=TokenUsage(2, 3, 5),
        completed_at=now + timedelta(seconds=2),
    )

    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        await unit_of_work.conversation_repository.add(conversation)
        await unit_of_work.turn_repository.add(first_turn)
        for message in conversation.messages:
            await unit_of_work.message_repository.add(message)

        async with SqlAlchemyConversationUnitOfWork(session_factory) as observer:
            assert (
                await observer.conversation_repository.get_by_id(conversation.id)
                is None
            )
            await observer.rollback()
        await unit_of_work.commit()

    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        loaded = await unit_of_work.conversation_repository.get_by_id(conversation.id)
        assert isinstance(loaded, Conversation)
        assert not isinstance(loaded, ConversationModel)
        assert loaded.next_sequence == 3
        by_key = await unit_of_work.turn_repository.get_by_idempotency_key(
            conversation.id,
            "idempotency-one",
        )
        assert by_key is not None and by_key.id == first_turn.id
        first_page = await unit_of_work.message_repository.list_by_conversation(
            conversation.id,
            limit=1,
        )
        second_page = await unit_of_work.message_repository.list_by_conversation(
            conversation.id,
            after_sequence=first_page[-1].sequence,
            limit=1,
        )
        assert [message.sequence for message in first_page] == [1]
        assert [message.sequence for message in second_page] == [2]
        context = (
            await unit_of_work.message_repository.list_recent_completed_for_context(
                conversation.id,
                limit=10,
            )
        )
        assert [message.sequence for message in context] == [1, 2]
        assert (
            await unit_of_work.message_repository.next_sequence(conversation.id)
            == 3
        )

        assert loaded is not None
        second_turn = loaded.start_turn(
            user_content="pending integration message",
            request_id="shared-request-id",
            idempotency_key="idempotency-two",
            created_at=now + timedelta(seconds=3),
        )
        await unit_of_work.conversation_repository.save(loaded)
        await unit_of_work.turn_repository.add(second_turn)
        await unit_of_work.message_repository.add(second_turn.user_message)
        await unit_of_work.commit()

    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        repeated_request_turn = (
            await unit_of_work.turn_repository.get_by_idempotency_key(
                conversation.id,
                "idempotency-two",
            )
        )
        assert repeated_request_turn is not None
        assert repeated_request_turn.request_id == "shared-request-id"
        pending = await unit_of_work.turn_repository.list_pending(
            conversation.id,
            limit=10,
        )
        assert [turn.id for turn in pending] == [repeated_request_turn.id]
        all_messages = await unit_of_work.message_repository.list_by_conversation(
            conversation.id,
            limit=10,
        )
        assert [message.sequence for message in all_messages] == [1, 2, 3]
        context = (
            await unit_of_work.message_repository.list_recent_completed_for_context(
                conversation.id,
                limit=10,
            )
        )
        assert [message.sequence for message in context] == [1, 2]

        locked = await unit_of_work.conversation_repository.get_for_update(
            conversation.id
        )
        assert locked is not None
        locked.archive(archived_at=now + timedelta(seconds=4))
        await unit_of_work.conversation_repository.save(locked)
        await unit_of_work.commit()

    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        archived = await unit_of_work.conversation_repository.get_by_id(
            conversation.id
        )
        assert archived is not None
        assert archived.status is ConversationStatus.ARCHIVED
        await unit_of_work.rollback()

    rolled_back = Conversation.create(
        title="Rolled back",
        created_at=now + timedelta(seconds=5),
    )
    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        await unit_of_work.conversation_repository.add(rolled_back)
        await unit_of_work.rollback()
    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        assert await unit_of_work.conversation_repository.get_by_id(rolled_back.id) is None
        await unit_of_work.rollback()

    implicit_rollback = Conversation.create(
        title="Implicit rollback",
        created_at=now + timedelta(seconds=6),
    )
    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        await unit_of_work.conversation_repository.add(implicit_rollback)
    async with SqlAlchemyConversationUnitOfWork(session_factory) as unit_of_work:
        assert (
            await unit_of_work.conversation_repository.get_by_id(implicit_rollback.id)
            is None
        )
        await unit_of_work.rollback()

    await _verify_row_lock(session_factory, conversation.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_base_repository_crud(migrated_database_url: str) -> None:
    """Exercise transaction-neutral CRUD against the migrated PostgreSQL schema."""

    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            repository = BaseRepository[SystemInfo, int](SystemInfo, session)
            key = f"repository-test-{uuid4().hex}"

            created = await repository.create(SystemInfo(key=key, value="created"))
            assert created.id > 0
            assert created.created_at is not None
            assert created.updated_at is not None

            fetched = await repository.get(created.id)
            assert fetched is created

            records = await repository.list(offset=0, limit=10)
            assert [record.id for record in records] == [created.id]

            updated = await repository.update(created.id, {"value": "updated"})
            assert updated is created
            assert updated.value == "updated"

            assert await repository.delete(created.id) is True
            assert await repository.get(created.id) is None
            assert await repository.delete(created.id) is False

            await session.rollback()

        await _verify_conversation_repositories(session_factory)
    finally:
        await engine.dispose()
