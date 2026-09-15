"""Unit tests for bounded load measurement and thresholds."""

import pytest

from packages.observability.load import LoadReport, run_load
from scripts.measure_load import HttpOperation, report_passes

pytestmark = pytest.mark.unit


def test_load_report_aggregates_successes_failures_and_statuses() -> None:
    def operation(index: int) -> int:
        if index == 1:
            raise TimeoutError
        return 200 if index < 3 else 503

    report = run_load(operation, request_count=4, concurrency=2)

    assert report.success_count == 2
    assert report.failure_count == 2
    assert report.failure_rate == 0.5
    assert report.status_counts == {"200": 2, "503": 1, "transport_error": 1}
    assert report.p50_latency_ms <= report.p95_latency_ms <= report.max_latency_ms
    assert report.requests_per_second > 0


@pytest.mark.parametrize(
    ("request_count", "concurrency"),
    [(0, 1), (100_001, 1), (1, 0), (1, 2), (257, 257)],
)
def test_load_runner_rejects_unbounded_inputs(request_count: int, concurrency: int) -> None:
    with pytest.raises(ValueError):
        run_load(lambda _: 200, request_count=request_count, concurrency=concurrency)


def test_thresholds_are_explicit() -> None:
    report = LoadReport(
        request_count=10,
        concurrency=2,
        success_count=9,
        failure_count=1,
        failure_rate=0.1,
        elapsed_seconds=1.0,
        requests_per_second=10.0,
        p50_latency_ms=10.0,
        p95_latency_ms=20.0,
        p99_latency_ms=20.0,
        max_latency_ms=20.0,
        status_counts={"200": 9, "503": 1},
    )

    assert report_passes(
        report,
        max_failure_rate=0.1,
        max_p95_ms=20.0,
        min_requests_per_second=10.0,
    )
    assert not report_passes(
        report,
        max_failure_rate=0.0,
        max_p95_ms=None,
        min_requests_per_second=None,
    )


@pytest.mark.parametrize(
    ("base_url", "path"),
    [
        ("ftp://localhost", "/health/live"),
        ("http://agenthub.example", "/health/live"),
        ("https://agenthub.example", "health/live"),
        ("https://agenthub.example", "//other.example/path"),
    ],
)
def test_http_operation_rejects_unsafe_targets(base_url: str, path: str) -> None:
    with pytest.raises(ValueError):
        HttpOperation(base_url, path, 1.0)
