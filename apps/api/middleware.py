"""HTTP middleware for correlation and bounded access logging."""

import logging
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from apps.api.logging import correlation_id_context

logger = logging.getLogger("agenthub.api.access")

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_correlation_id(candidate: str | None) -> str:
    """Accept a bounded trace-friendly ID or create a fresh opaque value."""
    if candidate and _VALID_CORRELATION_ID.fullmatch(candidate):
        return candidate
    return str(uuid4())


async def correlation_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Bind a correlation ID to the request, response, and application logs."""
    correlation_id = normalize_correlation_id(request.headers.get(CORRELATION_HEADER))
    request.state.correlation_id = correlation_id
    token = correlation_id_context.set(correlation_id)
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[CORRELATION_HEADER] = correlation_id
        return response
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        logger.info(
            "request_completed",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )
        correlation_id_context.reset(token)
