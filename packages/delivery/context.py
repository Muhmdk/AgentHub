"""Dependency-neutral execution context for shadow side-effect isolation."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from packages.contracts.governance import ToolAccess
from packages.contracts.runtime import AgentErrorCode, AgentExecutionError

_shadow_execution: ContextVar[bool] = ContextVar("agenthub_shadow_execution", default=False)


@contextmanager
def bind_shadow_execution() -> Iterator[None]:
    """Mark nested model and tool calls as candidate-only shadow work."""
    token = _shadow_execution.set(True)
    try:
        yield
    finally:
        _shadow_execution.reset(token)


def ensure_shadow_tool_access(access: ToolAccess) -> None:
    """Fail before authorization or invocation when shadow code requests a write."""
    if _shadow_execution.get() and access is ToolAccess.WRITE:
        raise AgentExecutionError(
            AgentErrorCode.POLICY_DENIED,
            "Shadow executions cannot invoke write tools",
        )
