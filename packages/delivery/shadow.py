"""Asynchronous shadow execution with hard side-effect and latency isolation."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from packages.contracts.delivery import ShadowPairRecord, ShadowStatus, TrafficRoute
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    AgentRequest,
    AgentResponse,
)
from packages.delivery.context import bind_shadow_execution
from packages.governance.privacy import redact_text


class AgentTarget(Protocol):
    """Agent invocation surface used by stable and candidate releases."""

    async def invoke(self, request: AgentRequest) -> AgentResponse: ...


class ShadowRecordSink(Protocol):
    """Asynchronous destination for completed shadow pairs."""

    async def record(self, pair: ShadowPairRecord) -> None: ...


class InMemoryShadowRecordSink:
    """Deterministic local sink used by development and tests."""

    def __init__(self) -> None:
        self.records: list[ShadowPairRecord] = []

    async def record(self, pair: ShadowPairRecord) -> None:
        self.records.append(pair)


class ShadowDispatcher:
    """Return stable output while a sampled, redacted candidate runs independently."""

    _SAMPLE_NAMESPACE = "agenthub.delivery.shadow.sample.v1"
    _REQUEST_NAMESPACE = "agenthub.delivery.shadow.request.v1"

    def __init__(
        self,
        sink: ShadowRecordSink,
        *,
        sample_rate_basis_points: int = 10_000,
        timeout_seconds: float = 2.0,
    ) -> None:
        if not 0 <= sample_rate_basis_points <= 10_000:
            raise ValueError("Shadow sample rate must be between 0 and 10000 basis points")
        if timeout_seconds <= 0:
            raise ValueError("Shadow timeout must be positive")
        self._sink = sink
        self._sample_rate_basis_points = sample_rate_basis_points
        self._timeout_seconds = timeout_seconds
        self._tasks: set[asyncio.Task[None]] = set()

    async def invoke(
        self,
        *,
        stable: AgentTarget,
        candidate: AgentTarget | None,
        route: TrafficRoute,
        request: AgentRequest,
        correlation_id: str,
        sampling_key: str,
    ) -> AgentResponse:
        """Invoke stable synchronously and enqueue eligible candidate work afterward."""
        stable_started = perf_counter()
        stable_response = await stable.invoke(request)
        stable_latency_ms = (perf_counter() - stable_started) * 1000
        candidate_target = route.allocation.candidate
        if candidate is None or candidate_target is None or not self._sampled(route, sampling_key):
            return stable_response

        redacted_request = request.model_copy(update={"query": redact_text(request.query)})
        task = asyncio.create_task(
            self._run_shadow(
                candidate=candidate,
                route=route,
                request=redacted_request,
                request_redacted=redacted_request.query != request.query,
                stable_response=stable_response,
                stable_latency_ms=stable_latency_ms,
                correlation_id=correlation_id,
                request_hash=self._request_hash(route, request),
            ),
            name=f"shadow:{route.id}:{correlation_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._consume_task)
        return stable_response

    async def drain(self) -> None:
        """Wait for currently scheduled shadow work without accepting its output."""
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def cancel_pending(self) -> None:
        """Cancel in-flight shadow work and wait for cancellation evidence to flush."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _sampled(self, route: TrafficRoute, sampling_key: str) -> bool:
        if not sampling_key or not sampling_key.strip():
            return False
        digest = hashlib.sha256(
            f"{self._SAMPLE_NAMESPACE}:{route.id}:{sampling_key}".encode()
        ).digest()
        return int.from_bytes(digest[:8]) % 10_000 < self._sample_rate_basis_points

    @classmethod
    def _request_hash(cls, route: TrafficRoute, request: AgentRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(
            f"{cls._REQUEST_NAMESPACE}:{route.id}:{canonical}".encode()
        ).hexdigest()

    async def _run_shadow(
        self,
        *,
        candidate: AgentTarget,
        route: TrafficRoute,
        request: AgentRequest,
        request_redacted: bool,
        stable_response: AgentResponse,
        stable_latency_ms: float,
        correlation_id: str,
        request_hash: str,
    ) -> None:
        started = perf_counter()
        response: AgentResponse | None = None
        error_code: str | None = None
        try:
            with bind_shadow_execution():
                response = await asyncio.wait_for(
                    candidate.invoke(request), timeout=self._timeout_seconds
                )
            status = ShadowStatus.SUCCEEDED
        except TimeoutError:
            status = ShadowStatus.TIMED_OUT
            error_code = AgentErrorCode.EXECUTION_TIMEOUT.value
        except asyncio.CancelledError:
            status = ShadowStatus.CANCELLED
            error_code = "cancelled"
        except AgentExecutionError as exc:
            status = ShadowStatus.FAILED
            error_code = exc.code.value
        except Exception as exc:
            status = ShadowStatus.FAILED
            error_code = type(exc).__name__

        candidate_target = route.allocation.candidate
        assert candidate_target is not None
        await self._sink.record(
            ShadowPairRecord(
                id=uuid4(),
                correlation_id=correlation_id,
                route_id=route.id,
                route_revision=route.revision,
                stable_release_id=route.allocation.stable.release_id,
                candidate_release_id=candidate_target.release_id,
                request_hash=request_hash,
                request_redacted=request_redacted,
                stable_response=stable_response,
                candidate_response=response,
                shadow_status=status,
                shadow_error_code=error_code,
                stable_latency_ms=stable_latency_ms,
                shadow_latency_ms=(perf_counter() - started) * 1000,
                recorded_at=datetime.now(UTC),
            )
        )

    def _consume_task(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()
