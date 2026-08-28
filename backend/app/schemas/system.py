"""Response contracts for service metadata endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness response returned while the process is running."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    """Readiness response returned when the service can accept traffic."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"] = "ready"


class VersionResponse(BaseModel):
    """Public service version response."""

    model_config = ConfigDict(frozen=True)

    version: str

