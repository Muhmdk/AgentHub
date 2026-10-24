"""Measure a small, explicit set of agent gateway requests without printing content."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from packages.observability.load import LoadReport, run_load

SCENARIOS = (
    (
        "inventory-agent",
        "Which Toronto stores may run low on snow shovels this weekend?",
        "Queen Street may run low",
    ),
    (
        "knowledge-agent",
        "Can I return an unopened product after 20 days?",
        "within 30 days",
    ),
    (
        "shopping-agent",
        "Recommend a snow shovel under $50",
        "NorthPeak Aluminum Snow Shovel",
    ),
)


@dataclass(frozen=True)
class AgentSample:
    """Only bounded outcome metadata, never an answer or submitted prompt."""

    agent_name: str
    status_code: int
    citations: int
    structure_valid: bool
    fixture_match: bool
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class AgentLoadReport:
    """Load plus content-free quality and usage aggregates."""

    measured_at_utc: str
    python_version: str
    machine: str
    target_kind: str
    fixture_checks: bool
    load: LoadReport
    structurally_valid: int
    cited_responses: int
    fixture_matches: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    per_agent_requests: dict[str, int]
    per_agent_structurally_valid: dict[str, int]


class AgentHttpOperation:
    """Send fixed requests through the same authenticated gateway as users."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        allow_remote: bool = False,
    ) -> None:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL must be an HTTP or HTTPS origin")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Base URL must not contain credentials, a path, query, or fragment")
        local = parsed.hostname in {"localhost", "127.0.0.1"}
        if not local and (parsed.scheme != "https" or not allow_remote):
            raise ValueError("Remote agent measurements require HTTPS and --allow-remote")
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Timeout must be greater than zero and no more than 30 seconds")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self.target_kind = "loopback" if local else "remote"
        self._timeout_seconds = timeout_seconds
        self._token = os.getenv("AGENTHUB_LOAD_BEARER_TOKEN")
        self._identity = os.getenv("AGENTHUB_LOAD_IDENTITY") or (
            "local/benchmark" if local else None
        )
        if not local and (not self._token or not self._identity):
            raise ValueError("Remote measurement requires bearer token and identity variables")
        self.samples: list[AgentSample] = []
        self._lock = Lock()

    def __call__(self, request_index: int) -> int:
        agent, query, expected = SCENARIOS[request_index % len(SCENARIOS)]
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Correlation-ID": f"agent-benchmark-{request_index}",
        }
        if self._identity:
            headers["X-AgentHub-Identity"] = self._identity
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(
            f"{self._origin}/gateway/agents/{agent}/invoke",
            data=json.dumps({"query": query, "seed": 6}).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status = int(response.status)
                body = json.load(response)
        except HTTPError as exc:
            return int(exc.code)
        if not isinstance(body, dict):
            body = {}
        citations = body.get("citations")
        usage = body.get("usage")
        answer = body.get("answer")
        citation_count = len(citations) if isinstance(citations, list) else 0
        usage = usage if isinstance(usage, dict) else {}
        structure_valid = bool(isinstance(answer, str) and answer and citation_count)
        sample = AgentSample(
            agent_name=agent,
            status_code=status,
            citations=citation_count,
            structure_valid=structure_valid,
            fixture_match=isinstance(answer, str) and expected.casefold() in answer.casefold(),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            estimated_cost_usd=float(usage.get("estimated_cost_usd", 0)),
        )
        with self._lock:
            self.samples.append(sample)
        return status


def measure_agents(
    operation: AgentHttpOperation,
    *,
    repeats: int,
    concurrency: int,
    fixture_checks: bool,
) -> AgentLoadReport:
    """Measure each scenario equally, with bounds stricter than generic HTTP load."""
    if not 1 <= repeats <= 50:
        raise ValueError("Repeats must be between 1 and 50")
    if not 1 <= concurrency <= min(4, len(SCENARIOS) * repeats):
        raise ValueError("Concurrency must be between 1 and 4, and no more than requests")
    load = run_load(
        operation,
        request_count=len(SCENARIOS) * repeats,
        concurrency=concurrency,
    )
    samples = operation.samples
    return AgentLoadReport(
        measured_at_utc=datetime.now(UTC).isoformat(),
        python_version=platform.python_version(),
        machine=platform.machine(),
        target_kind=operation.target_kind,
        fixture_checks=fixture_checks,
        load=load,
        structurally_valid=sum(item.structure_valid for item in samples),
        cited_responses=sum(item.citations > 0 for item in samples),
        fixture_matches=sum(item.fixture_match for item in samples),
        input_tokens=sum(item.input_tokens for item in samples),
        output_tokens=sum(item.output_tokens for item in samples),
        estimated_cost_usd=round(sum(item.estimated_cost_usd for item in samples), 8),
        per_agent_requests=dict(sorted(Counter(item.agent_name for item in samples).items())),
        per_agent_structurally_valid=dict(
            sorted(Counter(item.agent_name for item in samples if item.structure_valid).items())
        ),
    )


def report_passes(report: AgentLoadReport, *, max_p95_ms: float | None = None) -> bool:
    """Require successful HTTP, grounded structure, and explicit optional latency."""
    requests = report.load.request_count
    return (
        report.load.failure_count == 0
        and report.structurally_valid == requests
        and (not report.fixture_checks or report.fixture_matches == requests)
        and (max_p95_ms is None or report.load.p95_latency_ms <= max_p95_ms)
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--no-fixture-checks", action="store_true")
    parser.add_argument(
        "--acknowledge-invocations",
        action="store_true",
        help="acknowledge that this sends agent requests and may incur provider costs",
    )
    parsed = parser.parse_args(arguments)
    if not parsed.acknowledge_invocations:
        parser.error("Pass --acknowledge-invocations before sending agent requests")
    if parsed.max_p95_ms is not None and parsed.max_p95_ms <= 0:
        parser.error("--max-p95-ms must be greater than zero")
    try:
        operation = AgentHttpOperation(
            parsed.base_url,
            timeout_seconds=parsed.timeout_seconds,
            allow_remote=parsed.allow_remote,
        )
        report = measure_agents(
            operation,
            repeats=parsed.repeats,
            concurrency=parsed.concurrency,
            fixture_checks=not parsed.no_fixture_checks,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report_passes(report, max_p95_ms=parsed.max_p95_ms) else 1


if __name__ == "__main__":
    sys.exit(main())
