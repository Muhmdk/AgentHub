# AgentHub

AgentHub is an enterprise AgentOps and ModelOps control plane for registering,
evaluating, deploying, observing, governing, and operating AI agents. The project
is being delivered in twelve independently reviewable phases described in
[AGENTHUB_PLAN.md](AGENTHUB_PLAN.md).

## Current status

Phase 00 provides the local development foundation and a working control-plane API.
The repository currently includes:

- FastAPI liveness, readiness, and version endpoints;
- typed environment configuration with safe local defaults;
- JSON application and access logs with correlation IDs;
- consistent, non-sensitive API error envelopes;
- unit, contract, and process-level smoke tests;
- linting, formatting, strict typing, coverage, secret scanning, and dependency auditing;
- a least-privilege GitHub Actions CI workflow.

Agents, persistence, evaluation, governance, deployment, and the operator console are
planned for later phases and are not represented as implemented here.

## Prerequisites

- Python 3.14
- GNU Make
- Git

No cloud account, provider credential, model API key, container runtime, or database is
needed for Phase 00.

## Quick start

From a clean clone:

```bash
make setup
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
{"service":"agenthub-api","version":"0.1.0","environment":"local"}
```

Stop the foreground server with `Ctrl-C`. Interactive API documentation is available at
`http://127.0.0.1:8000/docs` while the service is running.

## API contracts

| Endpoint | Purpose | Success status |
|---|---|---:|
| `GET /health/live` | Confirms the process can serve requests | `200` |
| `GET /health/ready` | Confirms current Phase 00 dependencies are ready | `200` |
| `GET /version` | Reports service, build version, and environment | `200` |

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

## Configuration

Copy `.env.example` to `.env` only when local overrides are useful. Environment variables
take the same names and take precedence.

| Variable | Default | Allowed values or constraints |
|---|---|---|
| `AGENTHUB_ENVIRONMENT` | `local` | `local`, `test`, `staging`, `production` |
| `AGENTHUB_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `AGENTHUB_API_HOST` | `127.0.0.1` | Non-empty host string |
| `AGENTHUB_API_PORT` | `8000` | `1` through `65535` |

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
| `make run` | Run the API in the foreground |
| `make down` | Explain how to stop the foreground Phase 00 service |

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
[ADR 0001](docs/adr/0001-modular-monolith.md).

## Repository layout

```text
apps/api/                  FastAPI composition root and transport behavior
packages/contracts/        Shared health, metadata, and error schemas
tests/unit/                Configuration and logging behavior
tests/contract/            HTTP response contracts
tests/e2e/                 Real server-process smoke test
docs/adr/                  Accepted architectural decisions
```

PostgreSQL is intentionally deferred until registry persistence is implemented in Phase 03.
See [CONTRIBUTING.md](CONTRIBUTING.md) before making changes.

## License

AgentHub is available under the [MIT License](LICENSE).
