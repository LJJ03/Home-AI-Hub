"""Version 1 API router composition."""

from fastapi import APIRouter

from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.conversations import router as conversations_router


router = APIRouter()
router.include_router(chat_router)
router.include_router(conversations_router)


__all__ = ("router",)
