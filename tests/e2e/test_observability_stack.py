"""Opt-in live smoke test for the local OpenTelemetry pipeline."""

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[2]
TRACE_ID = "70f5a01305be4c84a4f4c8524e078b6b"  # pragma: allowlist secret

pytestmark = [
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("AGENTHUB_TEST_OBSERVABILITY_STACK") != "1",
        reason="requires the local observability Compose stack",
    ),
]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _json_request(url: str, *, data: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Content-Type": "application/json",
            "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
            "X-Correlation-ID": "otel-stack-smoke",
            "X-AgentHub-Release-ID": "phase-05-smoke",
        },
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return cast(dict[str, Any], json.load(response))


def _eventually(
    url: str,
    predicate: Callable[[dict[str, Any]], bool],
    timeout: float = 15,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = _json_request(url)
            if predicate(last):
                return last
        except urllib.error.URLError, TimeoutError:
            pass
        time.sleep(0.25)
    pytest.fail(f"observability result did not arrive before timeout: {last}")


def test_trace_and_metric_reach_local_backends() -> None:
    port = _available_port()
    environment = os.environ.copy()
    environment.update(
        {
            "AGENTHUB_ENVIRONMENT": "test",
            "AGENTHUB_API_PORT": str(port),
            "AGENTHUB_OTEL_ENABLED": "true",
            "AGENTHUB_OTEL_ENDPOINT": "http://127.0.0.1:4318",
            "AGENTHUB_OTEL_EXPORT_INTERVAL_MS": "500",
        }
    )
    process = subprocess.Popen(
        [".venv/bin/python", "-m", "apps.api"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    try:
        _eventually(f"{endpoint}/health/ready", lambda body: body.get("status") == "ready")
        result = _json_request(
            f"{endpoint}/agents/knowledge/invoke",
            data={"query": "Can I return an unopened product after 20 days?"},
        )
        assert "within 30 days" in str(result["answer"])

        trace = _eventually(
            f"http://127.0.0.1:3200/api/traces/{TRACE_ID}",
            lambda body: bool(body.get("batches")),
        )
        names = {
            span["name"]
            for batch in trace["batches"]
            for scope in batch["scopeSpans"]
            for span in scope["spans"]
        }
        assert names >= {"HTTP POST", "agent.invoke", "rag.retrieve", "model.generate"}

        query = urllib.parse.urlencode({"query": "agenthub_agent_requests_total"})
        metrics = _eventually(
            f"http://127.0.0.1:9090/api/v1/query?{query}",
            lambda body: bool(body.get("data", {}).get("result")),
        )
        assert metrics["status"] == "success"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
