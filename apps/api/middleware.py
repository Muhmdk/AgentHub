"""HTTP middleware for correlation and bounded access logging."""

import logging
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from opentelemetry.trace import SpanKind

from apps.api.logging import correlation_id_context
from packages.observability.conventions import Attribute
from packages.observability.telemetry import Telemetry

logger = logging.getLogger("agenthub.api.access")

CORRELATION_HEADER = "X-Correlation-ID"
RELEASE_HEADER = "X-AgentHub-Release-ID"
TRACE_HEADER = "X-Trace-ID"
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
    telemetry: Telemetry = request.app.state.telemetry
    correlation_id = normalize_correlation_id(request.headers.get(CORRELATION_HEADER))
    release_id = normalize_release_id(request.headers.get(RELEASE_HEADER))
    request.state.correlation_id = correlation_id
    request.state.release_id = release_id
    token = correlation_id_context.set(correlation_id)
    started_at = time.perf_counter()
    status_code = 500
    parent = telemetry.extract(request.headers)
    attributes = {
        Attribute.HTTP_METHOD: request.method,
        Attribute.CORRELATION_ID: correlation_id,
        Attribute.RELEASE_ID: release_id,
    }
    with telemetry.span(
        f"HTTP {request.method}", attributes, kind=SpanKind.SERVER, parent=parent
    ) as server_span:
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[CORRELATION_HEADER] = correlation_id
            trace_id = telemetry.trace_id()
            if trace_id is not None:
                response.headers[TRACE_HEADER] = trace_id
            carrier: dict[str, str] = {}
            telemetry.inject(carrier)
            if "traceparent" in carrier:
                response.headers["traceparent"] = carrier["traceparent"]
            return response
        finally:
            route = request.scope.get("route")
            route_pattern = getattr(route, "path", "unmatched")
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            server_span.set_attribute(Attribute.HTTP_ROUTE.value, route_pattern)
            server_span.set_attribute(Attribute.HTTP_STATUS_CODE.value, status_code)
            telemetry.record_http(
                {
                    Attribute.HTTP_METHOD: request.method,
                    Attribute.HTTP_ROUTE: route_pattern,
                    Attribute.HTTP_STATUS_CODE: status_code,
                },
                duration_ms,
            )
            logger.info(
                "request_completed",
                extra={
                    "http_method": request.method,
                    "path": route_pattern,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "trace_id": telemetry.trace_id(),
                },
            )
            correlation_id_context.reset(token)


def normalize_release_id(candidate: str | None) -> str:
    """Keep release context bounded without inventing release attribution."""
    if candidate and _VALID_CORRELATION_ID.fullmatch(candidate):
        return candidate
    return "unreleased"
