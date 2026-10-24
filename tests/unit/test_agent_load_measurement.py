"""Bounded agent measurements report latency and quality without leaking content."""

import io
import json
from urllib.request import Request

import pytest

from scripts.measure_agents import AgentHttpOperation, main, measure_agents, report_passes

pytestmark = pytest.mark.unit


class Response(io.BytesIO):
    status = 200


def test_agent_measurement_uses_gateway_and_aggregates_grounded_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTHUB_LOAD_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("AGENTHUB_LOAD_IDENTITY", raising=False)
    called: list[str] = []
    answers = {
        "inventory-agent": "Queen Street may run low on shovels.",
        "knowledge-agent": "Returns are accepted within 30 days.",
        "shopping-agent": "Try the NorthPeak Aluminum Snow Shovel.",
    }

    def fake_open(request: Request, timeout: float) -> Response:
        assert timeout == 2
        assert request.get_header("X-agenthub-identity") == "local/benchmark"
        agent = request.full_url.split("/")[-2]
        called.append(agent)
        assert isinstance(request.data, bytes)
        assert json.loads(request.data)["query"]
        return Response(
            json.dumps(
                {
                    "answer": answers[agent],
                    "citations": [{"source_id": "source", "title": "Evidence"}],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "estimated_cost_usd": 0,
                    },
                }
            ).encode()
        )

    monkeypatch.setattr("scripts.measure_agents.urlopen", fake_open)
    operation = AgentHttpOperation("http://127.0.0.1:8000", timeout_seconds=2)
    report = measure_agents(operation, repeats=2, concurrency=2, fixture_checks=True)

    assert report.load.request_count == 6
    assert report.load.failure_count == 0
    assert report.structurally_valid == 6
    assert report.cited_responses == 6
    assert report.fixture_matches == 6
    assert report.input_tokens == 60
    assert report.output_tokens == 30
    assert report.per_agent_requests == dict.fromkeys(answers, 2)
    assert sorted(called) == sorted(list(answers) * 2)
    assert report_passes(report)
    assert not report_passes(report, max_p95_ms=0.001)


def test_missing_citation_fails_quality_even_with_http_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(request: Request, timeout: float) -> Response:
        del request, timeout
        return Response(
            json.dumps(
                {"answer": "An answer", "citations": [], "usage": {"input_tokens": 1}}
            ).encode()
        )

    monkeypatch.setattr("scripts.measure_agents.urlopen", fake_open)
    report = measure_agents(
        AgentHttpOperation("http://localhost:8000", timeout_seconds=1),
        repeats=1,
        concurrency=1,
        fixture_checks=False,
    )
    assert report.load.failure_count == 0
    assert report.structurally_valid == 0
    assert not report_passes(report)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost:8000",
        "http://example.com",
        "https://example.com",
        "http://localhost:8000/other",
        "http://user@localhost:8000",
    ],
)
def test_agent_load_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        AgentHttpOperation(url, timeout_seconds=2)


def test_cli_requires_explicit_invocation_acknowledgement() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--base-url", "http://localhost:8000"])
    assert raised.value.code == 2
