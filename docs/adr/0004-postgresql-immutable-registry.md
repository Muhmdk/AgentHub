# ADR 0004: Persist immutable registry versions in PostgreSQL

- Status: Accepted
- Date: 2026-09-08
- Owners: AgentHub maintainers

## Context

AgentHub now needs a durable control-plane identity for each agent and executable version.
Registration must be idempotent under concurrency, lifecycle changes must reject stale writers,
and audit history must survive process restarts. The data has relational uniqueness and
referential-integrity requirements, while complete versioned manifests and audit details remain
naturally structured JSON.

An in-memory store would make the console misleading and could not prove database constraints,
concurrent registration, migrations, or append-only history. A separate registry service would
add a network boundary without a measured deployment need.

## Decision

The modular-monolith API uses PostgreSQL through SQLAlchemy and psycopg. Alembic owns
transactional migrations. A local Compose service publishes PostgreSQL on host port `5433`,
while CI starts a clean PostgreSQL service and migrates it before tests.

`agents` stores stable logical identities. `agent_versions` stores the complete JSON manifest
plus indexed identity fields, a canonical SHA-256 manifest hash, lifecycle state, and optimistic
state revision. The database enforces unique agent names and semantic versions, immutable source
SHAs and image digests, valid lifecycle and risk values, and non-mutability of version metadata.
Only lifecycle state and revision may change after registration.

Registration uses PostgreSQL conflict handling inside a transaction. Identical concurrent
requests converge on one version and one registration audit event. Reusing an agent version with
a different manifest returns a conflict. Lifecycle transitions lock the version row, check the
expected revision, consult one explicit state table, update state, and append the audit event in
the same transaction.

Audit rows record actor, timestamp, old and new state, request correlation ID, manifest hash, and
optional reason. A database trigger rejects updates and deletes, making the table append-only
beyond the application boundary.

## Consequences

Benefits:

- application validation is backed by relational constraints and immutable-record triggers;
- repeated and concurrent registration is deterministic;
- state changes and their audit evidence commit atomically;
- the UI and API read actual persisted records;
- clean-database migration is exercised in CI.

Tradeoffs:

- local Phase 03 development now requires Docker and PostgreSQL;
- synchronous database work is moved to worker threads at the async API boundary;
- the console is a focused inventory view rather than a complete administration interface;
- authentication and authorization are intentionally deferred to the governance phase, so the
  actor field is auditable input rather than a verified identity claim.
