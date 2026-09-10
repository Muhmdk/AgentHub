# AgentHub

AgentHub is an enterprise AgentOps and ModelOps control plane for registering,
evaluating, deploying, observing, governing, and operating AI agents. The project
is being delivered in twelve independently reviewable phases described in
[AGENTHUB_PLAN.md](AGENTHUB_PLAN.md).

## Current status

Phases 00 through 06 provide the local development foundation, three bounded demonstration
agents, an immutable registry, reproducible evaluations, an observability/SLO plane, and an
immutable CI/CD release path.
The repository currently includes:

- FastAPI liveness, readiness, and version endpoints;
- typed environment configuration with safe local defaults;
- JSON application and access logs with correlation IDs;
- consistent, non-sensitive API error envelopes;
- a deterministic fake model behind a provider-neutral interface;
- a bounded LangGraph Inventory Agent with four typed, read-only retail tools;
- a deterministic, versioned local retrieval pipeline with idempotent ingestion;
- grounded Knowledge and Shopping Agents with citations, abstention, and retrieval traces;
- a versioned six-query retrieval benchmark and prompt-injection defenses;
- a PostgreSQL registry for immutable agent versions and lifecycle state;
- idempotent manifest registration, optimistic concurrency, and append-only audits;
- registry APIs and a small operator inventory view backed by persisted data;
- versioned evaluation datasets, suites, evaluator versions, and release-gate profiles;
- bounded case execution with timeouts, safe failures, integrity hashes, and replay;
- deterministic quality, grounding, tool, safety, latency, token, and cost evaluators;
- immutable PostgreSQL evaluation artifacts with absolute and relative gate reasons;
- evaluation APIs, JSON/JUnit CLI output, and an operator comparison view;
- privacy-safe OpenTelemetry traces with W3C propagation and release correlation;
- bounded agent, tool, retrieval, model, evaluation, policy, token, and cost metrics;
- versioned SLOs, error budgets, multi-window burn alerts, and incident runbooks;
- a local Collector, Prometheus, Tempo, and provisioned Grafana dashboards;
- immutable candidate provenance and an idempotent, guarded promotion state machine;
- split PR, candidate-evaluation, release, and infrastructure workflows;
- non-root reproducible images, digest publication, high/critical scan gates, SBOMs, and attestations;
- protected staging and production approvals backed by short-lived GitHub OIDC identity;
- synthetic store, SKU, inventory, sales, promotion, and weather evidence;
- unit, contract, and process-level smoke tests;
- linting, formatting, strict typing, coverage, secret scanning, and dependency auditing;
- least-privilege, SHA-pinned GitHub Actions workflows.

Advanced policy-as-code, progressive delivery, and incident automation are planned for later
phases and are not represented as implemented here.

## Prerequisites

- Python 3.14
- GNU Make
- Git
- Docker with Compose

No cloud account, provider credential, or model API key is needed. Phase 03 uses the documented
local PostgreSQL container; host port `5433` avoids the common default PostgreSQL port.

## Inventory Agent demo

Run the deterministic reference question:

```bash
make demo-inventory
```

The command answers “Which Toronto stores may run low on snow shovels this weekend?” using
only committed synthetic evidence. It reports Queen Street as at risk and York Mills as not
currently at risk, followed by the four tool calls, their source IDs, citations, and normalized
fake-model usage. See the [Inventory Agent walkthrough](docs/demos/inventory-agent.md) for the
calculation, limitations, API example, and alternate CLI inputs.

## RAG agent demos

Validate and ingest the committed corpus, run both grounded agents, and measure retrieval:

```bash
make ingest-corpus
make demo-knowledge
make demo-shopping
make benchmark-rag
```

The Knowledge Agent answers a returns-policy question. The Shopping Agent recommends a snow
shovel under a stated budget using only `product.search`. Both return document citations and a
retrieval trace. The benchmark currently finds all six expected documents in its top-three
results. See the [RAG agent walkthrough](docs/demos/rag-agents.md) for HTTP examples, corpus
provenance, safety behavior, and limitations.

## Quick start

From a clean clone:

```bash
make setup
make up
make migrate
make seed-registry
make test
make run
```

`make setup` creates `.venv`, installs the pinned `uv` bootstrap tool, and installs the
cross-platform dependency set from `uv.lock`. The API then listens on
`http://127.0.0.1:8000`. In a second terminal, verify it:

```bash
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/version
```

Expected responses:

```json
{"status":"ok","service":"agenthub-api"}
{"status":"ready","service":"agenthub-api"}
{"service":"agenthub-api","version":"0.3.0","environment":"local"}
```

Stop the foreground server with `Ctrl-C`. Interactive API documentation is available at
`http://127.0.0.1:8000/docs` while the service is running. The registry console is available at
`http://127.0.0.1:8000/registry`; evaluation comparison is at
`http://127.0.0.1:8000/evaluations`; fleet health is at
`http://127.0.0.1:8000/observability`. Run `make down` when local services are no longer needed.

For local traces, metrics, dashboards, SLOs, alerts, and runbooks, see the
[observability guide](docs/observability.md).

## Evaluation and release gates

Run the default Inventory Agent suite and print its immutable JSON report:

```bash
make evaluate
```

The command exits `0` when execution completes and every gate passes. A deterministic known-bad
candidate demonstrates release blocking and exits `2`:

```bash
make evaluate-bad
```

Use `python -m packages.evaluation --help` to select another agent, emit JUnit, compare against a
stored baseline, or replay an existing run by UUID. The [evaluation guide](docs/evaluations.md)
documents metrics, thresholds, artifacts, APIs, replay, and model-judge limits.

Run the complete local candidate path with PostgreSQL running:

```bash
make simulate-release
make simulate-release-bad  # intentionally exits 2 before approval
```

The passing path registers the manifest, evaluates the candidate, attaches deterministic
security, policy, SBOM, and build evidence, then advances the same immutable release through
`evaluated → approved → staged → production`. The blocked path persists its failed evidence but
cannot leave `evaluated`. See the [release pipeline guide](docs/releases.md) and
[failed-workflow recovery runbook](docs/runbooks/release-recovery.md).

## API contracts

| Endpoint | Purpose | Success status |
|---|---|---:|
| `GET /health/live` | Confirms the process can serve requests | `200` |
| `GET /health/ready` | Confirms current process dependencies are ready | `200` |
| `GET /version` | Reports service, build version, and environment | `200` |
| `POST /agents/inventory/invoke` | Runs the bounded Inventory Agent | `200` |
| `POST /agents/knowledge/invoke` | Answers from trusted policy evidence or abstains | `200` |
| `POST /agents/shopping/invoke` | Recommends a retrieved product through `product.search` | `200` |
| `POST /registry/agents` | Idempotently registers an immutable manifest | `200` |
| `GET /registry/agents` | Lists persisted agent identities and current state | `200` |
| `GET /registry/agents/{name}` | Gets one agent summary | `200` |
| `GET /registry/agents/{name}/versions` | Lists immutable version history | `200` |
| `GET /registry/agents/{name}/versions/{version}` | Gets a complete manifest version | `200` |
| `POST /registry/agents/{name}/versions/{version}/transitions` | Applies a legal lifecycle change | `200` |
| `GET /registry/agents/{name}/versions/{version}/audit` | Lists append-only registry events | `200` |
| `POST /evaluations/runs` | Evaluates one registered candidate with a versioned suite | `200` |
| `GET /evaluations/runs` | Lists evaluation summaries, optionally filtered by agent | `200` |
| `GET /evaluations/runs/{run_id}` | Replays one immutable full report | `200` |
| `GET /evaluations/runs/{run_id}/comparison` | Gets absolute and relative gate checks | `200` |
| `POST /releases/candidates` | Idempotently creates a candidate with immutable evidence | `200` |
| `GET /releases` | Lists releases, optionally filtered by agent | `200` |
| `GET /releases/{release_id}` | Gets release state, gates, and provenance | `200` |
| `POST /releases/{release_id}/transitions` | Applies one guarded, retry-safe promotion | `200` |
| `GET /releases/{release_id}/events` | Lists append-only state events | `200` |
| `GET /releases/{release_id}/notes` | Generates release notes from stored provenance | `200` |
| `GET /observability/fleet` | Reports live fleet signals, SLOs, budgets, and burn rates | `200` |
| `GET /observability/agents/{name}` | Reports one agent's observability detail | `200` |

Clients may provide `X-Correlation-ID` using letters, numbers, `.`, `_`, `:`, or `-`, up
to 128 characters. AgentHub returns the accepted ID in the response. Missing or unsafe
values are replaced with a generated UUID.

Errors use one envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "correlation_id": "demo-request-1",
    "details": []
  }
}
```

Submitted values and internal exception details are not returned in error responses.

Invoke the agent over HTTP:

```bash
curl -s http://127.0.0.1:8000/agents/inventory/invoke \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: inventory-demo-1' \
  -d '{"query":"Which Toronto stores may run low on snow shovels this weekend?","seed":7,"as_of":"2026-09-08"}'
```

## Configuration

Copy `.env.example` to `.env` only when local overrides are useful. Environment variables
take the same names and take precedence.

| Variable | Default | Allowed values or constraints |
|---|---|---|
| `AGENTHUB_ENVIRONMENT` | `local` | `local`, `test`, `staging`, `production` |
| `AGENTHUB_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `AGENTHUB_API_HOST` | `127.0.0.1` | Non-empty host string |
| `AGENTHUB_API_PORT` | `8000` | `1` through `65535` |
| `AGENTHUB_MODEL_PROVIDER` | `fake` | `fake` |
| `AGENTHUB_AGENT_MAX_STEPS` | `3` | `1` through `20` |
| `AGENTHUB_TOOL_TIMEOUT_SECONDS` | `1.0` | Greater than `0`, at most `30` |
| `AGENTHUB_AGENT_TIMEOUT_SECONDS` | `5.0` | Greater than `0`, at most `120` |
| `AGENTHUB_RAG_TOP_K` | `3` | `1` through `20` |
| `AGENTHUB_RAG_MINIMUM_SCORE` | `0.15` | `0` through `1` |
| `AGENTHUB_RETRIEVAL_TIMEOUT_SECONDS` | `5.0` | Greater than `0`, at most `120` |
| `AGENTHUB_OTEL_ENABLED` | `false` | Enable bounded OTLP trace and metric export |
| `AGENTHUB_OTEL_ENDPOINT` | `http://127.0.0.1:4318` | Collector OTLP/HTTP base URL |
| `AGENTHUB_OTEL_EXPORT_INTERVAL_MS` | `5000` | `100` through `60000` |
| `AGENTHUB_OTEL_MAX_QUEUE_SIZE` | `256` | `64` through `4096` |
| `AGENTHUB_DATABASE_URL` | Local PostgreSQL on port `5433` | SQLAlchemy PostgreSQL URL |

Malformed configuration stops startup with the invalid field and error category. The
submitted value is deliberately omitted so a mistaken secret cannot be echoed.

## Development commands

| Command | Behavior |
|---|---|
| `make setup` | Create the virtual environment and install locked dependencies |
| `make format` | Apply Ruff formatting and safe lint fixes |
| `make lint` | Verify formatting and lint rules |
| `make typecheck` | Run strict mypy checks |
| `make test` | Run the complete test suite with coverage |
| `make test-unit` | Run isolated unit tests |
| `make test-contract` | Run API contract tests |
| `make test-integration` | Run component/process integration tests |
| `make test-e2e` | Run the process-level readiness smoke test |
| `make security` | Scan tracked files for secrets and audit dependencies |
| `make up` | Start and health-check the local PostgreSQL container |
| `make observability-up` | Start PostgreSQL, Collector, Prometheus, Tempo, and Grafana |
| `make observability-down` | Stop the observability services and leave PostgreSQL running |
| `make migrate` | Upgrade the configured database to the latest Alembic revision |
| `make seed-registry` | Idempotently register the three committed demo manifests |
| `make run` | Run the API in the foreground |
| `make demo-inventory` | Run the deterministic Inventory Agent CLI |
| `make demo-knowledge` | Run the grounded Knowledge Agent CLI |
| `make demo-shopping` | Run the grounded Shopping Agent CLI |
| `make ingest-corpus` | Validate ingestion and verify unchanged chunks are not duplicated |
| `make benchmark-rag` | Print the versioned known-answer retrieval report |
| `make evaluate` | Evaluate the Inventory Agent and emit an immutable JSON report |
| `make evaluate-bad` | Prove a known-bad candidate is blocked with metric-level reasons |
| `make simulate-release` | Run the passing candidate-to-production path locally |
| `make simulate-release-bad` | Prove a regressed candidate cannot be promoted |
| `make down` | Stop the local PostgreSQL container without deleting its volume |

Run `make lock` after deliberately changing dependencies in `pyproject.toml`, then commit
the resulting `uv.lock` change with the dependency change.

## Architecture principles

- Start as a modular monolith and extract services only from measured operational needs.
- Keep domain contracts under `packages/`; application entry points compose them under
  `apps/`.
- Keep local development deterministic and independent of cloud credentials or paid calls.
- Add only the directories and dependencies owned by the active phase.
- Put volatile provider integrations behind narrow adapters when a phase has real consumers.
- Treat configuration, logs, and errors as security boundaries: validate early and do not
  expose secrets, submitted values, raw prompts, or PII by default.
- Keep `main` runnable and make each change independently understandable and tested.

The architectural decision and its tradeoffs are recorded in
[ADR 0001](docs/adr/0001-modular-monolith.md) and
[ADR 0002](docs/adr/0002-provider-neutral-agent-runtime.md). The local retrieval decision is
recorded in [ADR 0003](docs/adr/0003-deterministic-local-retrieval.md), and registry persistence
in [ADR 0004](docs/adr/0004-postgresql-immutable-registry.md). Evaluation and release-gate
determinism is recorded in [ADR 0005](docs/adr/0005-deterministic-evaluation-gates.md).

## Repository layout

```text
apps/api/                  FastAPI composition root and transport behavior
apps/web/                  Registry and evaluation operator views backed by API calls
packages/contracts/        Shared runtime, retrieval, evaluation, health, and error schemas
packages/registry/         PostgreSQL repository, lifecycle, bootstrap, and records
packages/evaluation/       Runner, evaluators, gates, persistence, service, and CLI
packages/release/          Candidate provenance, guarded state, persistence, service, and CLI
agents/shared/             Provider-neutral model, retrieval, corpus, and benchmark code
agents/inventory/          Bounded graph, CLI, and read-only retail tools
agents/knowledge/          Grounded policy-question agent and CLI
agents/shopping/           Grounded recommendation agent, product tool, and CLI
data/synthetic/            Versioned fictional retail evidence
data/evals/                Versioned datasets, suites, gates, and retrieval fixtures
data/manifests/            Versioned manifests for the three demonstration agents
migrations/                Alembic environment and transactional schema revisions
schemas/                   Published Agent Manifest JSON Schema
tests/unit/                Configuration and logging behavior
tests/contract/            HTTP response contracts
tests/integration/         PostgreSQL repository, migration, API, and concurrency checks
tests/e2e/                 Real server-process smoke test
docs/adr/                  Accepted architectural decisions
docs/demos/                Reproducible operator demonstrations
```

Manifest fields, legal lifecycle transitions, audit guarantees, and API examples are documented
in the [registry guide](docs/registry/manifests-and-lifecycle.md). See
[CONTRIBUTING.md](CONTRIBUTING.md) before making changes.

## License

AgentHub is available under the [MIT License](LICENSE).
