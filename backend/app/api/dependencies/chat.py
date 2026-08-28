"""FastAPI dependency adapter for the stateless Chat application service."""

from fastapi import Request

from app.llm.service import LLMService
from app.services import ChatService


def get_chat_service(request: Request) -> ChatService:
    """Build a stateless Chat service from the lifespan-owned LLM service."""

    llm_service = getattr(request.app.state, "llm_service", None)
    if not isinstance(llm_service, LLMService):
        raise RuntimeError("LLM service is not initialized")
    return ChatService(llm_service)


__all__ = ("get_chat_service",)
