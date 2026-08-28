"""FastAPI application factory and ASGI application object."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import DatabaseManager
from app.llm.bootstrap import bootstrap_llm
from app.llm.config import LLMSettings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own database, LLM, and application startup and shutdown lifecycles."""

    settings = cast(Settings, application.state.settings)
    llm_settings = cast(LLMSettings, application.state.llm_settings)
    logger = logging.getLogger(__name__)
    database_manager = DatabaseManager(settings)
    database_manager.start()
    application.state.database_manager = database_manager

    try:
        llm_service = bootstrap_llm(llm_settings)
    except BaseException:
        try:
            await database_manager.stop()
        finally:
            del application.state.database_manager
        raise

    application.state.llm_service = llm_service
    logger.info(
        "Application started",
        extra={"environment": settings.environment, "version": settings.version},
    )
    try:
        yield
    finally:
        try:
            await llm_service.aclose()
        finally:
            del application.state.llm_service
            try:
                await database_manager.stop()
            finally:
                del application.state.database_manager
                logger.info("Application stopped")


def create_app(
    settings: Settings | None = None,
    *,
    llm_settings: LLMSettings | None = None,
) -> FastAPI:
    """Build and configure a FastAPI application instance."""

    resolved_settings = settings if settings is not None else get_settings()
    resolved_llm_settings = (
        llm_settings if llm_settings is not None else LLMSettings()
    )
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.name,
        version=resolved_settings.version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.llm_settings = resolved_llm_settings
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
