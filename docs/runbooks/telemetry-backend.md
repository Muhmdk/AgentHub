# Telemetry backend failure response

Use this runbook when `AgentHubTelemetryCollectorMissing` fires, Grafana panels have no data, or
trace lookup fails.

## Diagnose

```bash
docker compose ps
curl -fsS http://127.0.0.1:13133/
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3200/ready
curl -fsS http://127.0.0.1:3000/api/health
docker compose logs --tail=100 otel-collector prometheus tempo grafana
```

Check that Prometheus reports the `agenthub-otel-collector` target as up and that the AgentHub
process uses `AGENTHUB_OTEL_ENABLED=true` with `AGENTHUB_OTEL_ENDPOINT=http://127.0.0.1:4318`.

## Recover

Restart only the failed local service with `docker compose restart <service>`. If configuration
changed, run `docker compose up --detach <service>` so Compose recreates it. Validate Prometheus
configuration and rules with:

```bash
docker compose exec -T prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec -T prometheus promtool test rules /etc/prometheus/alerts.test.yml
```

AgentHub request handling is deliberately isolated from exporter failures. Do not restart a
healthy API merely because telemetry is unavailable. The SDK queue and local observation store
are bounded, so recovery does not require clearing an unbounded backlog.
