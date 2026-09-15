# Architecture and dependency audit

This audit covers the Phase 10 system at merge commit `c1b0f30`. It evaluates runtime ownership,
dependency direction, configuration flags, assets, infrastructure, and executable entry points.

## Dependency direction

| Layer | Owns | May depend on |
|---|---|---|
| `packages/contracts` | immutable transport and domain types | Pydantic and standard library |
| `packages/*` | domain services, repositories, provider-neutral ports | contracts and narrow adapters |
| `agents/*` | bounded agent graphs and tools | domain contracts and provider ports |
| `apps/*` | HTTP/gateway composition and operator pages | agents and packages |
| `migrations/*` | schema registration and ordered DDL | SQLAlchemy record modules only |
| `scripts/*` | reproducible operator and CI entry points | public application/domain modules |

No domain package imports `apps`. Provider clients remain behind the model, retrieval, policy,
telemetry, and database ports. The modular monolith still has one transactional PostgreSQL boundary;
there is no measured need for a distributed service split.

## Findings and disposition

| Area | Evidence | Disposition |
|---|---|---|
| Incident package initializer | Alembic loaded analysis, LangGraph, policy, and rollback services while importing records | Removed eager re-exports; migrations now load the record module directly |
| Runtime dependencies | Every production dependency has a source import and a runtime or deployment consumer | Retained; no dependency removed |
| Configuration flags | Provider, gateway, governance, retry, budget, retrieval, telemetry, and database settings are read by composition or adapters | Retained; no orphan setting found |
| Local compatibility routes | Direct `/agents/*/invoke` routes are used by committed demos and are restricted to local/test | Retained and truthfully marked deprecated |
| Web assets | All five HTML consoles are returned by an API route and covered by contract tests | Retained; no placeholder asset found |
| Terraform and Helm | Modules are referenced by the dev environment or validation jobs; outputs feed documented deployment steps | Retained; no unjustified resource found |
| Demo data | Manifests, evaluation data, corpus, inventory, and policy fixtures have deterministic test/demo consumers | Retained |
| Python source | Ruff, strict mypy, import searches, and the full coverage suite find no unused import or unreachable public entry point | Accepted |

## Boundaries intentionally retained

- `apps/api/main.py` is the composition root. It may instantiate concrete repositories and adapters,
  but domain decisions remain in `packages`.
- SQLAlchemy records share one registry metadata object so Alembic can detect cross-domain foreign
  keys and drift in one pass.
- Operator consoles remain dependency-free HTML/JavaScript served by FastAPI. They display persisted
  or live process data and do not embed fabricated values.
- Azure modules are a validated reference deployment. Local development and every deterministic
  lifecycle test remain cloud-credential free.

## Verification

The audit is rerun through `make lint`, `make typecheck`, `make test`, `make security`, `make policy`,
`make infra-validate`, Actionlint, and `alembic check`. Any new dependency, setting, asset, or
infrastructure resource must identify its production consumer in the same change.
