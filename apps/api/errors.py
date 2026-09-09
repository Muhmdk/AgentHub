"""Consistent, correlation-aware HTTP error handling."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from packages.contracts.errors import ErrorEnvelope, ErrorPayload, ValidationIssue
from packages.contracts.runtime import AgentErrorCode, AgentExecutionError

logger = logging.getLogger("agenthub.api.errors")

ExceptionHandler = Callable[[Request, Exception], Awaitable[Response]]


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unavailable")


def _response(status_code: int, payload: ErrorPayload) -> JSONResponse:
    envelope = ErrorEnvelope(error=payload)
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - framework contract
        raise TypeError("Expected StarletteHTTPException")

    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = "not_found" if exc.status_code == 404 else "http_error"
    return _response(
        exc.status_code,
        ErrorPayload(code=code, message=message, correlation_id=_correlation_id(request)),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - framework contract
        raise TypeError("Expected RequestValidationError")

    issues = [
        ValidationIssue(
            location=".".join(str(part) for part in error["loc"]),
            message=error["msg"],
            kind=error["type"],
        )
        for error in exc.errors()
    ]
    return _response(
        422,
        ErrorPayload(
            code="validation_error",
            message="Request validation failed",
            correlation_id=_correlation_id(request),
            details=issues,
        ),
    )


async def unexpected_exception_handler(request: Request, exc: Exception) -> Response:
    logger.error(
        "unhandled_request_error",
        extra={"error_type": type(exc).__name__, "path": request.url.path},
    )
    return _response(
        500,
        ErrorPayload(
            code="internal_error",
            message="An unexpected error occurred",
            correlation_id=_correlation_id(request),
        ),
    )


async def agent_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, AgentExecutionError):  # pragma: no cover - framework contract
        raise TypeError("Expected AgentExecutionError")

    status_by_code = {
        AgentErrorCode.INVALID_REQUEST: 422,
        AgentErrorCode.TOOL_ERROR: 502,
        AgentErrorCode.TOOL_TIMEOUT: 504,
        AgentErrorCode.EXECUTION_TIMEOUT: 504,
        AgentErrorCode.STEP_LIMIT: 500,
        AgentErrorCode.MODEL_ERROR: 502,
        AgentErrorCode.RETRIEVAL_ERROR: 502,
        AgentErrorCode.RETRIEVAL_TIMEOUT: 504,
    }
    logger.warning("agent_request_failed", extra={"error_code": exc.code.value})
    return _response(
        status_by_code[exc.code],
        ErrorPayload(
            code=exc.code.value,
            message=exc.message,
            correlation_id=_correlation_id(request),
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register all public API exception contracts."""
    handlers: tuple[tuple[type[Exception], ExceptionHandler], ...] = (
        (AgentExecutionError, agent_exception_handler),
        (StarletteHTTPException, http_exception_handler),
        (RequestValidationError, validation_exception_handler),
        (Exception, unexpected_exception_handler),
    )
    for exception_type, handler in handlers:
        app.add_exception_handler(exception_type, handler)
