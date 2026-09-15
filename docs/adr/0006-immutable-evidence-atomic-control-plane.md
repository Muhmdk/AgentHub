# ADR 0006: Couple control-plane transitions to immutable evidence and atomic audit

- Status: Accepted
- Date: 2026-09-14
- Owners: AgentHub maintainers

## Context

Evaluation, release, traffic, canary, incident, and rollback operations cross several
domain concepts. If a route could point to mutable candidate content, if a state update
could commit without its audit event, or if retries could create duplicate actions, an
operator could not reconstruct what reached production or safely recover it.

A distributed event system could separate these modules, but AgentHub has no measured
availability or scale requirement that outweighs the resulting partial-failure and local
development costs. The current PostgreSQL boundary can provide stronger consistency.

## Decision

Keep control-plane records in one PostgreSQL database and commit each accepted state
change with its event in one transaction. Reference agent versions, evaluations,
provenance, stable/candidate releases, and incident evidence by immutable identifiers and
hashes. Reject stale revisions and conflicting idempotency-key reuse. Enforce append-only
evidence/event tables with database constraints or triggers where the record model is
immutable.

Traffic replacement stores a complete stable/candidate allocation rather than a partial
patch. Canary actions atomically update their rollout and route. Rollback planning binds
the exact incident, route revision, canary revision, known-good release, and provenance
hash; execution revalidates those facts before changing traffic. A separate fixed-window
verification decides whether recovery succeeded or must escalate.

Telemetry can explain and alert, but it is not the source of truth for control-plane
state. Missing telemetry blocks safety-sensitive promotion and recovery decisions rather
than inventing a healthy value.

## Consequences

Benefits:

- retries converge without duplicate state transitions;
- every accepted transition has durable attribution and prior/new state;
- a rollback restores an existing immutable release instead of rebuilding it;
- incident findings can cite content-addressed evidence;
- local and CI tests exercise the same transaction semantics.

Tradeoffs:

- PostgreSQL is a shared availability and scaling boundary;
- cross-domain schema changes require coordinated migrations;
- event retention and archival need an explicit future policy;
- independent service extraction would require an outbox or equivalent consistency
  design and a superseding ADR.
