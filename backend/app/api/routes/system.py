"""Infrastructure endpoints for liveness, readiness, and version metadata."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies.database import get_database_manager
from app.core.config import Settings, get_settings
from app.core.exceptions import ApplicationError
from app.db.session import DatabaseManager, DatabaseUnavailableError
from app.schemas.system import HealthResponse, ReadyResponse, VersionResponse


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """Confirm that the API process is alive."""

    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse, summary="Readiness check")
async def ready(
    database_manager: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> ReadyResponse:
    """Confirm that the API and its required database are ready."""

    try:
        await database_manager.check_connection()
    except DatabaseUnavailableError as exc:
        raise ApplicationError(
            code="database_unavailable",
            message="Database is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    return ReadyResponse()


@router.get("/version", response_model=VersionResponse, summary="Service version")
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    """Return the configured public application version."""

    return VersionResponse(version=settings.version)
