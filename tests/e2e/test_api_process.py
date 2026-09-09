"""Process-level smoke test for the documented server entry point."""

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def running_api() -> Iterator[str]:
    port = _available_port()
    environment = os.environ.copy()
    environment["AGENTHUB_ENVIRONMENT"] = "test"
    environment["AGENTHUB_API_PORT"] = str(port)
    process = subprocess.Popen(
        [
            ".venv/bin/python",
            "-m",
            "apps.api",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"API stopped during startup:\n{stdout}\n{stderr}")
            try:
                with urllib.request.urlopen(f"{endpoint}/health/ready", timeout=0.25):
                    break
            except urllib.error.URLError, TimeoutError:
                time.sleep(0.05)
        else:
            pytest.fail("API did not become ready within 10 seconds")
        yield endpoint
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.integration
@pytest.mark.e2e
def test_server_process_reports_readiness(running_api: str) -> None:
    request = urllib.request.Request(
        f"{running_api}/health/ready", headers={"X-Correlation-ID": "process-smoke"}
    )

    with urllib.request.urlopen(request, timeout=2) as response:
        body = json.load(response)

    assert response.status == 200
    assert response.headers["X-Correlation-ID"] == "process-smoke"
    assert body == {"status": "ready", "service": "agenthub-api"}


@pytest.mark.integration
@pytest.mark.e2e
def test_server_process_invokes_inventory_agent(running_api: str) -> None:
    request = urllib.request.Request(
        f"{running_api}/agents/inventory/invoke",
        data=json.dumps(
            {"query": "Which Toronto stores may run low on snow shovels this weekend?"}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Correlation-ID": "inventory-process-smoke",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.load(response)

    assert response.status == 200
    assert "Queen Street may run low" in body["answer"]
    assert len(body["citations"]) == 6


@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.parametrize(
    ("agent", "query", "answer_fragment"),
    [
        ("knowledge", "Can I return an unopened product after 20 days?", "within 30 days"),
        ("shopping", "Recommend a snow shovel under $50", "NorthPeak Aluminum Snow Shovel"),
    ],
)
def test_server_process_invokes_grounded_agents(
    running_api: str, agent: str, query: str, answer_fragment: str
) -> None:
    request = urllib.request.Request(
        f"{running_api}/agents/{agent}/invoke",
        data=json.dumps({"query": query, "seed": 6}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.load(response)

    assert response.status == 200
    assert answer_fragment in body["answer"]
    assert body["citations"]
    assert body["retrieval"]["corpus_version"] == "v1"
