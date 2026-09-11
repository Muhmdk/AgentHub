"""Consistent, correlation-aware HTTP error handling."""

import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from packages.contracts.errors import ErrorEnvelope, ErrorPayload, ValidationIssue
from packages.contracts.runtime import AgentErrorCode, AgentExecutionError
from packages.delivery.repository import (
    DeliveryBlockedError,
    DeliveryConflictError,
    DeliveryNotFoundError,
)
from packages.evaluation.repository import EvaluationConflictError, EvaluationNotFoundError
from packages.evaluation.service import EvaluationTargetNotFoundError
from packages.incidents.evidence_repository import EvidenceConflictError
from packages.incidents.repository import IncidentConflictError, IncidentNotFoundError
from packages.registry.repository import RegistryConflictError, RegistryNotFoundError
from packages.release.repository import (
    ReleaseBlockedError,
    ReleaseConflictError,
    ReleaseNotFoundError,
)

logger = logging.getLogger("agenthub.api.errors")

ExceptionHandler = Callable[[Request, Exception], Awaitable[Response]]


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unavailable")


def _response(
    status_code: int,
    payload: ErrorPayload,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(error=payload)
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - framework contract
        raise TypeError("Expected StarletteHTTPException")

    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code_by_status = {
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
    }
    code = code_by_status.get(exc.status_code, "http_error")
    return _response(
        exc.status_code,
        ErrorPayload(code=code, message=message, correlation_id=_correlation_id(request)),
        headers=exc.headers,
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
        AgentErrorCode.POLICY_DENIED: 403,
        AgentErrorCode.POLICY_UNAVAILABLE: 503,
        AgentErrorCode.RATE_LIMITED: 429,
        AgentErrorCode.BUDGET_EXCEEDED: 429,
        AgentErrorCode.MODEL_TIMEOUT: 504,
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


async def registry_not_found_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RegistryNotFoundError):  # pragma: no cover - framework contract
        raise TypeError("Expected RegistryNotFoundError")
    return _response(
        404,
        ErrorPayload(
            code="registry_not_found",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def registry_conflict_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RegistryConflictError):  # pragma: no cover - framework contract
        raise TypeError("Expected RegistryConflictError")
    return _response(
        409,
        ErrorPayload(
            code="registry_conflict",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def evaluation_not_found_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, EvaluationNotFoundError):  # pragma: no cover
        raise TypeError("Expected EvaluationNotFoundError")
    return _response(
        404,
        ErrorPayload(
            code="evaluation_not_found",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def evaluation_conflict_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, EvaluationConflictError):  # pragma: no cover
        raise TypeError("Expected EvaluationConflictError")
    return _response(
        409,
        ErrorPayload(
            code="evaluation_conflict",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def evaluation_target_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, EvaluationTargetNotFoundError):  # pragma: no cover
        raise TypeError("Expected EvaluationTargetNotFoundError")
    return _response(
        422,
        ErrorPayload(
            code="evaluation_target_unavailable",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def release_not_found_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ReleaseNotFoundError):  # pragma: no cover
        raise TypeError("Expected ReleaseNotFoundError")
    return _response(
        404,
        ErrorPayload(
            code="release_not_found",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def release_conflict_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ReleaseConflictError):  # pragma: no cover
        raise TypeError("Expected ReleaseConflictError")
    return _response(
        409,
        ErrorPayload(
            code="release_conflict",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def release_blocked_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, ReleaseBlockedError):  # pragma: no cover
        raise TypeError("Expected ReleaseBlockedError")
    return _response(
        409,
        ErrorPayload(
            code="release_blocked",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def delivery_not_found_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, DeliveryNotFoundError):  # pragma: no cover
        raise TypeError("Expected DeliveryNotFoundError")
    return _response(
        404,
        ErrorPayload(
            code="delivery_not_found",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def delivery_conflict_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, DeliveryConflictError):  # pragma: no cover
        raise TypeError("Expected DeliveryConflictError")
    return _response(
        409,
        ErrorPayload(
            code="delivery_conflict",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def delivery_blocked_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, DeliveryBlockedError):  # pragma: no cover
        raise TypeError("Expected DeliveryBlockedError")
    return _response(
        409,
        ErrorPayload(
            code="delivery_blocked",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def incident_not_found_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, IncidentNotFoundError):  # pragma: no cover
        raise TypeError("Expected IncidentNotFoundError")
    return _response(
        404,
        ErrorPayload(
            code="incident_not_found",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


async def incident_conflict_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, IncidentConflictError | EvidenceConflictError):  # pragma: no cover
        raise TypeError("Expected incident persistence conflict")
    return _response(
        409,
        ErrorPayload(
            code="incident_conflict",
            message=str(exc),
            correlation_id=_correlation_id(request),
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register all public API exception contracts."""
    handlers: tuple[tuple[type[Exception], ExceptionHandler], ...] = (
        (AgentExecutionError, agent_exception_handler),
        (RegistryNotFoundError, registry_not_found_handler),
        (RegistryConflictError, registry_conflict_handler),
        (EvaluationNotFoundError, evaluation_not_found_handler),
        (EvaluationConflictError, evaluation_conflict_handler),
        (EvaluationTargetNotFoundError, evaluation_target_handler),
        (ReleaseNotFoundError, release_not_found_handler),
        (ReleaseConflictError, release_conflict_handler),
        (ReleaseBlockedError, release_blocked_handler),
        (DeliveryNotFoundError, delivery_not_found_handler),
        (DeliveryConflictError, delivery_conflict_handler),
        (DeliveryBlockedError, delivery_blocked_handler),
        (IncidentNotFoundError, incident_not_found_handler),
        (IncidentConflictError, incident_conflict_handler),
        (EvidenceConflictError, incident_conflict_handler),
        (StarletteHTTPException, http_exception_handler),
        (RequestValidationError, validation_exception_handler),
        (Exception, unexpected_exception_handler),
    )
    for exception_type, handler in handlers:
        app.add_exception_handler(exception_type, handler)
