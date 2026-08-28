"""Version 1 API router composition."""

from fastapi import APIRouter

from app.api.v1.routes.chat import router as chat_router


router = APIRouter()
router.include_router(chat_router)


__all__ = ("router",)
