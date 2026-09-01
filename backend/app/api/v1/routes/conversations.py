"""Version 1 HTTP adapter for persistent conversation resources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.conversations import (
    get_conversation_chat_service,
    get_conversation_command_service,
    get_conversation_query_service,
)
from app.api.error_mapping.conversations import map_conversation_exception
from app.application.conversations import (
    ArchiveConversationCommand,
    ConversationApplicationError,
    ConversationChatCommand,
    ConversationChatService,
    ConversationCommandService,
    ConversationQueryService,
    CreateConversationCommand,
)
from app.schemas.conversations import (
    ArchiveConversationResponse,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateTurnRequest,
    CreateTurnResponse,
    MessageListResponse,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
)
async def create_conversation(
    request_body: CreateConversationRequest,
    service: Annotated[
        ConversationCommandService,
        Depends(get_conversation_command_service),
    ],
) -> ConversationResponse:
    try:
        result = await service.create_conversation(
            CreateConversationCommand(title=request_body.title)
        )
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return ConversationResponse.from_application(result)


@router.get(
    "",
    response_model=ConversationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List conversations",
)
async def list_conversations(
    service: Annotated[
        ConversationQueryService,
        Depends(get_conversation_query_service),
    ],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConversationListResponse:
    try:
        result = await service.list_conversations(offset=offset, limit=limit)
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return ConversationListResponse.from_application(result)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a conversation",
)
async def get_conversation(
    conversation_id: UUID,
    service: Annotated[
        ConversationQueryService,
        Depends(get_conversation_query_service),
    ],
) -> ConversationResponse:
    try:
        result = await service.get_conversation(conversation_id)
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return ConversationResponse.from_application(result)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    status_code=status.HTTP_200_OK,
    summary="List conversation messages",
)
async def list_conversation_messages(
    conversation_id: UUID,
    service: Annotated[
        ConversationQueryService,
        Depends(get_conversation_query_service),
    ],
    after_sequence: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MessageListResponse:
    try:
        result = await service.list_messages(
            conversation_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return MessageListResponse.from_application(result)


@router.post(
    "/{conversation_id}/turns",
    response_model=CreateTurnResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a non-streaming conversation turn",
)
async def create_conversation_turn(
    conversation_id: UUID,
    request_body: CreateTurnRequest,
    service: Annotated[
        ConversationChatService,
        Depends(get_conversation_chat_service),
    ],
) -> CreateTurnResponse:
    try:
        result = await service.complete(
            ConversationChatCommand(
                conversation_id=conversation_id,
                user_content=request_body.content,
                idempotency_key=request_body.idempotency_key,
            )
        )
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return CreateTurnResponse.from_application(result)


@router.post(
    "/{conversation_id}/archive",
    response_model=ArchiveConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a conversation",
)
async def archive_conversation(
    conversation_id: UUID,
    service: Annotated[
        ConversationCommandService,
        Depends(get_conversation_command_service),
    ],
) -> ArchiveConversationResponse:
    try:
        result = await service.archive_conversation(
            ArchiveConversationCommand(conversation_id=conversation_id)
        )
    except ConversationApplicationError as exception:
        raise map_conversation_exception(exception) from None
    return ArchiveConversationResponse.from_application(result)


__all__ = ("router",)
