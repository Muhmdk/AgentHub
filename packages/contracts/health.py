"""Health and service metadata response contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness or readiness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "ready"]
    service: str


class VersionResponse(BaseModel):
    """Deployed service version metadata."""

    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    environment: Literal["local", "test", "staging", "production"]
