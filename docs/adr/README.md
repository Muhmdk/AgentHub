# Architecture decision records

ADRs record decisions that constrain implementation and operations. Accepted records
remain historical even when a later ADR supersedes them.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Accepted | Begin as a modular monolith and extract only from measured need |
| [0002](0002-provider-neutral-agent-runtime.md) | Accepted | Keep agent execution provider-neutral, bounded, and deterministic locally |
| [0003](0003-deterministic-local-retrieval.md) | Accepted | Use versioned deterministic in-memory retrieval for the local corpus |
| [0004](0004-postgresql-immutable-registry.md) | Accepted | Persist immutable registry versions and append-only audit in PostgreSQL |
| [0005](0005-deterministic-evaluation-gates.md) | Accepted | Make critical gates deterministic, explainable, replayable, and immutable |
| [0006](0006-immutable-evidence-atomic-control-plane.md) | Accepted | Couple control-plane state transitions to immutable evidence and atomic audit |

New ADRs use the next four-digit number and include status, date, context, decision,
consequences, and any superseded record. Material service extraction, consistency,
identity, provider-failover, or retention changes require an ADR before implementation.
