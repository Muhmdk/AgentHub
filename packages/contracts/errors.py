"""Public error response contracts."""

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    """One safe validation failure without the submitted value."""

    model_config = ConfigDict(extra="forbid")

    location: str
    message: str
    kind: str


class ErrorPayload(BaseModel):
    """Machine-readable API error."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    correlation_id: str
    details: list[ValidationIssue] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    """Top-level error response shape."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorPayload
