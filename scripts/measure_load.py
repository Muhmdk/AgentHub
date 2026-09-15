"""Measure a bounded HTTP load scenario without recording response content."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from packages.observability.load import LoadReport, run_load


class HttpOperation:
    """Issue one safe GET request for the load runner."""

    def __init__(self, base_url: str, path: str, timeout_seconds: float) -> None:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL must be an HTTP or HTTPS origin")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Non-local load targets must use HTTPS")
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Path must start with exactly one slash")
        self._url = (
            f"{urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))}{path}"
        )
        self._timeout_seconds = timeout_seconds
        self._bearer_token = os.getenv("AGENTHUB_LOAD_BEARER_TOKEN")
        self._identity = os.getenv("AGENTHUB_LOAD_IDENTITY")

    def __call__(self, request_index: int) -> int:
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": f"load-{request_index}",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        if self._identity:
            headers["X-AgentHub-Identity"] = self._identity
        try:
            with urlopen(
                Request(self._url, headers=headers), timeout=self._timeout_seconds
            ) as response:
                response.read()
                return int(response.status)
        except HTTPError as exc:
            return int(exc.code)


def report_passes(
    report: LoadReport,
    *,
    max_failure_rate: float,
    max_p95_ms: float | None,
    min_requests_per_second: float | None,
) -> bool:
    """Evaluate explicit scenario thresholds."""
    return (
        report.failure_rate <= max_failure_rate
        and (max_p95_ms is None or report.p95_latency_ms <= max_p95_ms)
        and (
            min_requests_per_second is None or report.requests_per_second >= min_requests_per_second
        )
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--path", default="/health/live")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--min-requests-per-second", type=float)
    parsed = parser.parse_args(arguments)
    if not 0 <= parsed.max_failure_rate <= 1:
        parser.error("--max-failure-rate must be between zero and one")
    if parsed.timeout_seconds <= 0 or parsed.timeout_seconds > 30:
        parser.error("--timeout-seconds must be greater than zero and no more than 30")
    if parsed.max_p95_ms is not None and parsed.max_p95_ms <= 0:
        parser.error("--max-p95-ms must be greater than zero")
    if parsed.min_requests_per_second is not None and parsed.min_requests_per_second <= 0:
        parser.error("--min-requests-per-second must be greater than zero")
    try:
        operation = HttpOperation(parsed.base_url, parsed.path, parsed.timeout_seconds)
        report = run_load(
            operation,
            request_count=parsed.requests,
            concurrency=parsed.concurrency,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return (
        0
        if report_passes(
            report,
            max_failure_rate=parsed.max_failure_rate,
            max_p95_ms=parsed.max_p95_ms,
            min_requests_per_second=parsed.min_requests_per_second,
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
