"""Provider-neutral contracts for model, tool, and agent execution."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatMessage(BaseModel):
    """One provider-neutral chat message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: NonEmptyString


class ModelRequest(BaseModel):
    """Bounded chat completion request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=1, le=8192)
    seed: int = 0


class Usage(BaseModel):
    """Provider usage returned without provider-specific fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class ModelResponse(BaseModel):
    """Normalized model response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    response_id: NonEmptyString
    model: NonEmptyString
    content: NonEmptyString
    usage: Usage


class ToolCall(BaseModel):
    """Validated request to invoke one declared tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: NonEmptyString
    name: NonEmptyString
    arguments: dict[str, JsonValue]


class Citation(BaseModel):
    """Stable reference to synthetic evidence used by an answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: NonEmptyString
    title: NonEmptyString


class ToolCallEvidence(BaseModel):
    """Auditable evidence for a completed read-only tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: NonEmptyString
    tool_name: NonEmptyString
    arguments: dict[str, JsonValue]
    source_ids: list[NonEmptyString]
    status: Literal["success", "no_data"]


class AgentRequest(BaseModel):
    """Synchronous user request accepted by a demonstration agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    seed: int = 0


class AgentResponse(BaseModel):
    """Agent answer with evidence and normalized usage, never hidden reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: NonEmptyString
    model: NonEmptyString
    citations: list[Citation]
    tool_calls: list[ToolCallEvidence]
    usage: Usage


class AgentErrorCode(StrEnum):
    """Stable failure categories exposed across transports."""

    INVALID_REQUEST = "invalid_request"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    EXECUTION_TIMEOUT = "execution_timeout"
    STEP_LIMIT = "step_limit"


class AgentExecutionError(RuntimeError):
    """Safe agent failure carrying a stable code and public message."""

    def __init__(self, code: AgentErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
