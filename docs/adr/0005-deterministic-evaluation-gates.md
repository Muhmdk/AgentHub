# ADR 0005: Deterministic evaluation and explainable release gates

- Status: Accepted
- Date: 2026-09-09

## Context

AgentHub must prevent weak or unsafe agent versions from advancing. A result is useful for release
control only when operators can reproduce its inputs, inspect failures, compare it with production,
and prove that the stored decision was not rewritten later. Provider-based judges alone cannot
provide those guarantees and are especially unsuitable as the sole authority for safety rules.

## Decision

Store datasets, suites, evaluator versions, and gate profiles as versioned repository artifacts.
Execute cases with bounded asynchronous concurrency and an independent deadline per case. Capture
normalized request and response data, continue after partial failure, and fail closed when a
critical result is missing, errored, or timed out.

Use deterministic evaluators for exact expectations, response schema, citations, tool names and
arguments, PII, harmful output, unauthorized tools, latency, tokens, and estimated cost. Permit
named, versioned model judges only through explicit dependency injection. Critical safety limits
remain deterministic.

Persist the full report and normalized case, aggregate, and gate rows in PostgreSQL. Attach each run
to an immutable agent-version foreign key, hash every versioned input and the final report, and use
database triggers to make evaluation artifacts append-only. Evaluate both absolute thresholds and,
when supplied, candidate-versus-baseline regression limits. Emit one human-readable reason per
check whether it passes or fails.

## Consequences

Release decisions are inspectable, CI-readable, and replayable without another provider call.
Known-bad candidates can be demonstrated locally. Timing remains environment-sensitive, regex
safety checks are deliberately incomplete, and dataset maintenance is required when agent behavior
or evidence changes. Semantic quality beyond explicit expectations may require an opt-in model
judge with its own provider and artifact controls.
