# Performance and resilience baseline

This report records a reproducible local baseline for AgentHub. It is evidence for
initial deployment sizing, not a production capacity promise. Production targets must
be re-measured with the chosen database, telemetry exporter, identity provider, model,
retrieval service, network, and representative request mix.

## Measurement method

Measurements were taken on 2026-09-14 EDT (2026-09-15 UTC) from the committed
single-process Uvicorn entry point, a local PostgreSQL database, deterministic local
model and retrieval providers, Python 3.14.3, and macOS 26.2 on an Apple M2 Pro with
12 logical CPUs and 16 GiB RAM. The client and server shared the same host, so these
results exclude network latency and are only a repeatable engineering baseline.

Start the API after applying migrations:

```console
make up
make migrate
make run
```

Run the same bounded scenarios from another terminal:

```console
make measure-load BASE_URL=http://127.0.0.1:8000 \
  LOAD_ARGS="--path /health/live --requests 500 --concurrency 20 \
  --max-failure-rate 0 --max-p95-ms 250 --min-requests-per-second 50"

make measure-load BASE_URL=http://127.0.0.1:8000 \
  LOAD_ARGS="--path /observability/fleet --requests 100 --concurrency 8 \
  --max-failure-rate 0 --max-p95-ms 1000 --min-requests-per-second 5"
```

For authenticated staging or production targets, set
`AGENTHUB_LOAD_BEARER_TOKEN` and `AGENTHUB_LOAD_IDENTITY` in the environment. The
tool accepts plain HTTP only for localhost, never prints response bodies or
credentials, and caps a run at 100,000 requests and 256 workers.

## Recorded results

| Scenario | Requests / concurrency | Failures | Throughput | p50 | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `GET /health/live` | 500 / 20 | 0 | 2,176.66 req/s | 7.30 ms | 26.52 ms | 37.60 ms | 42.95 ms |
| `GET /observability/fleet` | 100 / 8 | 0 | 285.46 req/s | 18.84 ms | 105.99 ms | 106.88 ms | 107.14 ms |

A separate 10,000-request health run at concurrency 20 sustained 2,626.27 req/s
with zero failures and 9.50 ms p95 latency. During that run the server process peaked
at 182,192 KiB RSS and approximately one logical CPU according to repeated `ps`
samples. Process logging remained enabled, matching the documented local entry point.

The process-level CI test sends 60 health requests at concurrency 8. Its thresholds
(zero failures, p95 below 1,000 ms, and more than 5 req/s) are intentionally wider
than this machine's measurements. They detect deadlocks, accidental serialization,
and gross regressions without pretending that a shared CI runner is a benchmark lab.

## Initial resource defaults

The Helm defaults now request 250 millicores and 256 MiB and limit the API to one CPU
and 512 MiB. The memory request is about 1.4 times the observed peak and the limit is
about 2.9 times that peak. The one-CPU limit reflects the measured single-process
saturation point; the 250-millicore request reserves capacity for ordinary control
plane traffic without scheduling every replica as continuously saturated.

These are starting values. Alert before sustained memory reaches 80% of the limit or
CPU throttling coincides with latency/error-budget burn. Scale replicas for sustained
CPU-bound load, and re-run this report before lowering requests, increasing Uvicorn
workers, or changing provider modes. The database pool is bounded to 5 persistent plus
10 overflow connections per replica, so replica count must be included in database
connection budgeting.

## Failure and recovery evidence

| Injected condition | Expected behavior | Automated evidence |
| --- | --- | --- |
| Database unavailable or schema stale | Readiness fails safely; liveness remains independent | `tests/contract/test_api.py` |
| Database pool exhausted | Checkout fails within configured timeout and recovers after release | `tests/integration/test_database_resilience.py` |
| Policy engine unavailable or denies | Gateway fails closed before model/tool execution and records a safe audit result | `tests/integration/test_governance_gateway.py`, `tests/unit/test_governance_audit.py` |
| Model timeout or provider failure | Work is cancelled or bounded; stable public error has no provider detail | `tests/integration/test_governance_gateway.py`, `tests/unit/test_governance_runtime.py` |
| Retrieval timeout or failure | Knowledge response fails safely without fabricated citations | `tests/unit/test_knowledge_agent.py` |
| Tool timeout or failure | Agent execution is bounded and returns a normalized error | `tests/unit/test_inventory_agent.py`, `tests/unit/test_shopping_agent.py` |
| Shadow candidate timeout/failure | Stable response is unaffected; only redacted failure state is recorded | `tests/unit/test_shadow_delivery.py` |
| Missing or unhealthy telemetry | Canary promotion fails closed without mutating rollout state | `tests/e2e/test_progressive_delivery.py` |
| Measured candidate regression | Guardrail blocks promotion; incident evidence supports known-good rollback | `tests/e2e/test_incident_rollback.py` |
| Shutdown begins | Readiness changes to draining before bounded dependency cleanup | application lifespan and `tests/contract/test_api.py` |

Database restore and migration verification are in
[`runbooks/database-recovery.md`](runbooks/database-recovery.md). Telemetry, policy,
release, and incident recovery procedures live beside it in `docs/runbooks/`.

## Known limits

- The baseline is loopback traffic with deterministic providers, not end-user agent
  invocation load.
- It does not measure Azure OpenAI, Azure AI Search, TLS, ingress, cross-zone database
  latency, or OpenTelemetry backend pressure.
- A single Uvicorn worker cannot use more than one CPU for Python-heavy work. Scale-out
  and multi-worker behavior require a deployment-specific test.
- RSS sampling is process-level and includes the imported provider SDKs; it is not a
  container cgroup measurement.
