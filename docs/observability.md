# Observability and service levels

AgentHub emits OpenTelemetry traces and metrics without recording prompts, model responses,
retrieval queries, tool arguments, credentials, or raw exception messages. Telemetry is disabled
by default so the API remains usable without an observability backend.

## Start the local stack

```bash
make observability-up
AGENTHUB_OTEL_ENABLED=true make run
```

The stack exposes:

| Surface | URL |
|---|---|
| AgentHub fleet view | `http://127.0.0.1:8000/observability` |
| Grafana | `http://127.0.0.1:3000` |
| Prometheus | `http://127.0.0.1:9090` |
| Tempo API | `http://127.0.0.1:3200` |
| Collector OTLP/HTTP | `http://127.0.0.1:4318` |

Grafana provisions Prometheus and Tempo data sources plus the **AgentHub Fleet Health** and
**AgentHub Agent Detail** dashboards. Anonymous local viewer access is enabled; the deployment is
for local development only.

Generate a trace with an explicit release and correlation boundary:

```bash
curl -s http://127.0.0.1:8000/agents/knowledge/invoke \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: observability-demo' \
  -H 'X-AgentHub-Release-ID: local-v1' \
  -d '{"query":"Can I return an unopened product after 20 days?"}'
```

The response returns `X-Trace-ID` and a W3C `traceparent`. The fleet view links its latest trace
to Grafana Explore. `make observability-down` stops only the observability services;
`make down` stops the complete Compose project without deleting its volumes.

## Semantic conventions and privacy

Trace attributes use a fixed allowlist for service, HTTP route, agent and prompt version, model
provider and deployment, tool name, retrieval corpus, release, correlation, token, cost, and
evaluation fields. Metric labels use a smaller allowlist and normalize invalid or unbounded
values to `unknown`. HTTP metrics use route templates, never raw request paths.

The process-local observation store and trace index are bounded. SDK export uses a bounded batch
queue, 500 ms export timeout, and failure isolation. If the Collector or a downstream backend is
unavailable, agent requests continue and excess telemetry is dropped rather than growing without
limit.

## Metrics and SLO profile

The metric surface covers request count/error/latency, tool calls/success/latency, retrieval
latency, model tokens and estimated cost, evaluation scores/gates, and policy denials. The
versioned profile at `data/slos/default-v1.json` defines 30-day objectives for:

- availability: 99%;
- latency: 95% at or below 3 seconds;
- tool success: 99%;
- groundedness: 95% at or above 0.95;
- evaluation pass rate: 95%;
- estimated cost: 99% at or below $0.025 per model call.

`GET /observability/fleet` returns fleet health and all objective calculations.
`GET /observability/agents/{agent_name}` returns one agent. An empty observation window is
reported as `null`, not as success.

Error-budget remaining is the unconsumed share of allowed bad events. Fast burn requires both the
5-minute and 1-hour windows to reach 14.4x. Slow burn requires both the 30-minute and 6-hour
windows to reach 6x. Prometheus applies the same availability windows. Validate the alert rules
and their forced-failure fixture with:

```bash
docker compose exec -T prometheus promtool test rules /etc/prometheus/alerts.test.yml
```

Run the opt-in process-to-backend smoke test while the stack is up:

```bash
AGENTHUB_TEST_OBSERVABILITY_STACK=1 \
  .venv/bin/pytest tests/e2e/test_observability_stack.py --no-cov
```

## Incident response

- Availability budget burn: [SLO burn-rate runbook](runbooks/slo-burn-rate.md)
- Missing or failing backends: [telemetry backend runbook](runbooks/telemetry-backend.md)

Keep the agent serving unless its own dependency is unhealthy. Observability loss alone is not a
reason to take the API out of service.
