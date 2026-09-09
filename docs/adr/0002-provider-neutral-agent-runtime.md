# ADR 0002: Keep the agent runtime provider-neutral and bounded

- Status: Accepted
- Date: 2026-09-08
- Owners: AgentHub maintainers

## Context

The first demonstration agent must prove that AgentHub can execute an inspectable workflow,
call typed tools, retain evidence, and produce repeatable results without cloud credentials or
paid model calls. Tying its graph directly to one model SDK would mix provider concerns into
domain behavior and make ordinary tests dependent on network availability, quotas, cost, and
non-deterministic output.

An unconstrained tool loop would also be inappropriate for the Inventory Agent. Its task has
four known read-only evidence sources, and every execution must have predictable timeout and
step boundaries.

## Decision

Agent code depends on the small `ChatModel` protocol and normalized request, response, usage,
tool, citation, and error contracts. Provider selection is explicit. Phase 01 permits only the
`fake` provider; an unsupported value fails configuration instead of silently falling back to a
network adapter.

The deterministic fake model hashes the complete seeded request to produce a replay identity
and returns the evidence-derived answer prepared by the graph. It does not make network calls.
Future provider adapters may generate the final answer, but they must preserve the same bounded
contract and will remain opt-in until their owning phase.

The Inventory Agent uses a three-node LangGraph sequence:

```text
plan → invoke declared read-only tools → build and return cited response
```

The runtime enforces a total deadline, an independent timeout for each tool, and a maximum step
count. The graph has no dynamic ability to select undeclared tools. Tool arguments and fixture
outputs are validated with typed schemas, and responses contain tool-call evidence rather than
hidden reasoning.

## Consequences

Benefits:

- default tests and demos are deterministic, offline, and free;
- provider SDK details do not leak into agent or API contracts;
- every tool call is predictable, bounded, read-only, and attributable to sources;
- timeout, failure, and no-data behavior can be tested exactly.

Tradeoffs:

- the fake model is not evidence that a hosted model will produce identical language;
- the fixed graph supports only the bounded inventory question family;
- adding a live provider requires a deliberate adapter and opt-in contract tests;
- richer planning is deferred until a real workload demonstrates the need.

