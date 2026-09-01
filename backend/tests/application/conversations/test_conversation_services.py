"""Offline tests for conversation command and query services."""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations import (
    ArchiveConversationCommand,
    ConversationCommandService,
    ConversationNotFoundError,
    ConversationQueryService,
    CreateConversationCommand,
)
from app.application.conversations import (
    ConversationChatCommand,
    ConversationChatService,
)
from app.domain.conversations import (
    Conversation,
    ConversationArchivedError,
    ConversationStatus,
)
from tests.application.conversations.fakes import (
    FakeLLMService,
    FakeUnitOfWorkFactory,
)


NOW = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_command_service_creates_and_archives_without_an_llm() -> None:
    factory = FakeUnitOfWorkFactory()
    service = ConversationCommandService(
        unit_of_work_factory=factory,
        clock=lambda: NOW,
    )

    created = await service.create_conversation(
        CreateConversationCommand(title="Offline"),
    )
    archived = await ConversationCommandService(
        unit_of_work_factory=factory,
        clock=lambda: NOW + timedelta(minutes=1),
    ).archive_conversation(ArchiveConversationCommand(created.id))

    assert created.status is ConversationStatus.ACTIVE
    assert archived.status is ConversationStatus.ARCHIVED
    assert factory.store.conversations[created.id].archived_at == archived.archived_at
    assert factory.store.events.count("uow.commit") == 2
    assert "llm.generate" not in factory.store.events


@pytest.mark.asyncio
async def test_command_service_reports_a_missing_conversation_safely() -> None:
    service = ConversationCommandService(
        unit_of_work_factory=FakeUnitOfWorkFactory(),
        clock=lambda: NOW,
    )
    missing_id = Conversation.create(created_at=NOW).id

    with pytest.raises(ConversationNotFoundError) as captured:
        await service.archive_conversation(ArchiveConversationCommand(missing_id))

    assert captured.value.code == "conversation_not_found"


@pytest.mark.asyncio
async def test_archived_conversation_rejects_chat_before_llm_call() -> None:
    conversation = Conversation.create(created_at=NOW)
    conversation.archive(archived_at=NOW + timedelta(minutes=1))
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = FakeLLMService(factory)
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(minutes=2),
    )

    with pytest.raises(ConversationArchivedError):
        await service.complete(
            ConversationChatCommand(
                conversation_id=conversation.id,
                user_content="must not be written",
            )
        )

    assert llm.requests == []
    assert factory.store.conversations[conversation.id].messages == ()


@pytest.mark.asyncio
async def test_query_service_returns_dtos_and_pages_messages_by_sequence() -> None:
    conversation = Conversation.create(title="Query", created_at=NOW)
    first = conversation.start_turn(
        user_content="first",
        created_at=NOW + timedelta(seconds=1),
    )
    conversation.complete_turn(
        first.id,
        assistant_content="answer",
        completed_at=NOW + timedelta(seconds=2),
    )
    second = conversation.start_turn(
        user_content="second",
        created_at=NOW + timedelta(seconds=3),
    )
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    service = ConversationQueryService(unit_of_work_factory=factory)

    view = await service.get_conversation(conversation.id)
    conversations = await service.list_conversations(offset=0, limit=10)
    first_page = await service.list_messages(conversation.id, limit=2)
    second_page = await service.list_messages(
        conversation.id,
        after_sequence=first_page.next_sequence,
        limit=2,
    )

    assert view.id == conversation.id
    assert conversations.items == (view,)
    assert [message.sequence for message in first_page.items] == [1, 2]
    assert [message.sequence for message in second_page.items] == [3]
    assert second_page.items[0].turn_id == second.id
    assert "content=" not in repr(second_page.items[0])
