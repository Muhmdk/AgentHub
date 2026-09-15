"""Bounded, dependency-free load measurement utilities."""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class LoadSample:
    """One measured request without response content or sensitive error details."""

    latency_ms: float
    status_code: int | None
    succeeded: bool


@dataclass(frozen=True)
class LoadReport:
    """Aggregate measurements for one bounded load scenario."""

    request_count: int
    concurrency: int
    success_count: int
    failure_count: int
    failure_rate: float
    elapsed_seconds: float
    requests_per_second: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    status_counts: dict[str, int]


RequestOperation = Callable[[int], int]


def _percentile(values: list[float], quantile: float) -> float:
    """Return a nearest-rank percentile from a non-empty sample."""
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _measure(operation: RequestOperation, request_index: int) -> LoadSample:
    started = time.perf_counter()
    try:
        status_code = operation(request_index)
        succeeded = 200 <= status_code < 400
    except Exception:
        status_code = None
        succeeded = False
    return LoadSample(
        latency_ms=(time.perf_counter() - started) * 1_000,
        status_code=status_code,
        succeeded=succeeded,
    )


def run_load(
    operation: RequestOperation,
    *,
    request_count: int,
    concurrency: int,
) -> LoadReport:
    """Run a bounded concurrent scenario and return content-free measurements."""
    if request_count < 1 or request_count > 100_000:
        raise ValueError("request_count must be between 1 and 100000")
    if concurrency < 1 or concurrency > min(request_count, 256):
        raise ValueError("concurrency must be between 1 and min(request_count, 256)")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        samples = list(executor.map(lambda index: _measure(operation, index), range(request_count)))
    elapsed_seconds = max(time.perf_counter() - started, 1e-9)

    latencies = [sample.latency_ms for sample in samples]
    success_count = sum(sample.succeeded for sample in samples)
    statuses = Counter(
        str(sample.status_code) if sample.status_code is not None else "transport_error"
        for sample in samples
    )
    return LoadReport(
        request_count=request_count,
        concurrency=concurrency,
        success_count=success_count,
        failure_count=request_count - success_count,
        failure_rate=(request_count - success_count) / request_count,
        elapsed_seconds=elapsed_seconds,
        requests_per_second=request_count / elapsed_seconds,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        p99_latency_ms=_percentile(latencies, 0.99),
        max_latency_ms=max(latencies),
        status_counts=dict(sorted(statuses.items())),
    )
