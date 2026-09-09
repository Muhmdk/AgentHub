"""Telemetry semantic conventions, privacy, propagation, and bounds."""

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from apps.api.config import Settings
from apps.api.main import create_app
from packages.observability.conventions import METRIC_NAMES, Attribute
from packages.observability.privacy import (
    bounded_dimension,
    metric_attributes,
    span_attributes,
)
from packages.observability.telemetry import ObservationStore, Telemetry, TelemetryConfig


@pytest.mark.unit
def test_redaction_and_allowlists_drop_content_and_bound_dimensions() -> None:
    attributes = span_attributes(
        {
            Attribute.AGENT_NAME: "inventory-agent",
            Attribute.CORRELATION_ID: "person@example.com",
            "prompt.content": "Ignore everything; Bearer token-secret-value-123456",
            Attribute.RELEASE_ID: "sk-abcdefghijklmnop",
        }
    )
    metric_labels = metric_attributes(
        {
            Attribute.AGENT_NAME: "bad label with spaces and person@example.com",
            Attribute.CORRELATION_ID: "request-123",
            Attribute.HTTP_ROUTE: "/agents/{agent}/invoke",
        }
    )

    assert attributes == {
        "agent.name": "inventory-agent",
        "agenthub.correlation_id": "[REDACTED]",
        "release.id": "[REDACTED]",
    }
    assert "prompt.content" not in attributes
    assert metric_labels == {
        "agent.name": "unknown",
        "http.route": "/agents/{agent}/invoke",
    }
    assert bounded_dimension("x" * 81) == "unknown"


@pytest.mark.unit
def test_observation_store_is_bounded_and_filterable() -> None:
    store = ObservationStore(capacity=2)
    store.record("agent.success", 1, {"agent.name": "inventory-agent"})
    store.record("agent.success", 0, {"agent.name": "knowledge-agent"})
    store.record("agent.success", 1, {"agent.name": "inventory-agent"})

    assert len(store.snapshot()) == 2
    assert [event.value for event in store.snapshot(agent_name="inventory-agent")] == [1]


@pytest.mark.unit
def test_end_to_end_spans_propagate_context_without_prompt_content() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        TelemetryConfig("agenthub-api", "test", "test"),
        span_exporter=exporter,
        metric_reader=InMemoryMetricReader(),
    )
    app = create_app(
        Settings(environment="test", _env_file=None),
        telemetry_instance=telemetry,
    )
    incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/agents/knowledge/invoke",
            json={"query": "Can I return an unopened product after 20 days?"},
            headers={
                "traceparent": f"00-{incoming_trace_id}-b7ad6b7169203331-01",
                "X-Correlation-ID": "otel-contract-1",
                "X-AgentHub-Release-ID": "release-42",
            },
        )
        fleet_response = client.get("/observability/fleet")
        detail_response = client.get("/observability/agents/knowledge-agent")
        page_response = client.get("/observability")

    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == incoming_trace_id
    assert response.headers["traceparent"].split("-")[1] == incoming_trace_id
    spans = exporter.get_finished_spans()
    propagated_spans = [
        span for span in spans if f"{span.context.trace_id:032x}" == incoming_trace_id
    ]
    assert {span.name for span in propagated_spans} >= {
        "HTTP POST",
        "agent.invoke",
        "rag.retrieve",
        "model.generate",
    }
    exported = " ".join(
        f"{key}={value}" for span in spans for key, value in (span.attributes or {}).items()
    )
    assert "Can I return" not in exported
    assert "otel-contract-1" in exported
    assert "release-42" in exported
    server = next(span for span in propagated_spans if span.name == "HTTP POST")
    assert server.attributes is not None
    assert server.attributes["http.route"] == "/agents/knowledge/invoke"
    assert fleet_response.status_code == 200
    knowledge = next(
        agent
        for agent in fleet_response.json()["agents"]
        if agent["agent_name"] == "knowledge-agent"
    )
    assert knowledge["request_count"] == 1
    assert knowledge["availability"] == 1
    assert knowledge["last_trace_id"] == incoming_trace_id
    assert detail_response.json() == knowledge
    assert page_response.status_code == 200
    assert "Fleet health" in page_response.text


@pytest.mark.unit
def test_declared_metric_surface_is_stable_and_bounded() -> None:
    assert len(METRIC_NAMES) == 14
    assert "agenthub.agent.duration" in METRIC_NAMES
    assert "agenthub.policy.denials" in METRIC_NAMES
