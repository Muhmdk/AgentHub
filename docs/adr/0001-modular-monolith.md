# ADR 0001: Begin as a modular monolith

- Status: Accepted
- Date: 2026-09-08
- Owners: AgentHub maintainers

## Context

AgentHub will eventually coordinate registry, evaluation, governance, delivery,
observability, and incident workflows. Those concerns need clear ownership, but the initial
product has no measured scaling, security, or release requirement that justifies separate
deployable services. Premature service boundaries would add network failure modes, duplicated
configuration, deployment coordination, and local infrastructure before they provide value.

The project must also remain usable without Azure credentials or paid model calls, and a new
developer should be able to start it locally in under fifteen minutes.

## Decision

AgentHub begins as a modular monolith. Domain behavior belongs in focused packages under
`packages/`; executable applications under `apps/` compose transports, configuration, and
dependencies. Packages communicate through typed contracts rather than application globals
or database internals.

A module may become an independently deployable service only after a measured load, security,
or release-isolation requirement demonstrates the need. Any extraction requires a new ADR that
defines ownership, failure behavior, data consistency, observability, and local-development
impact.

Phase 00 therefore ships one FastAPI process and no database. PostgreSQL is introduced when
the registry has real persistence behavior in Phase 03.

## Consequences

Benefits:

- local setup and testing remain fast and inexpensive;
- refactoring module boundaries does not require network or deployment migrations;
- cross-domain changes can remain transactional once persistence arrives;
- operational complexity grows only with demonstrated requirements.

Tradeoffs:

- package boundaries rely on review and tests rather than network isolation;
- all modules initially share one process lifecycle and scaling unit;
- an eventual extraction may require contract and data migration work.

These tradeoffs are acceptable for the current scope and are easier to reverse than an
unnecessary distributed architecture.
