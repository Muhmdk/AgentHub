# Changelog

All notable AgentHub changes are documented here. The project follows semantic
versioning; Git tags are created only from a green commit on `main`.

## 1.0.0 — 2026-09-15

### Added

- Three deterministic retail agents behind an authenticated, policy-authorized gateway.
- Immutable PostgreSQL registry, evaluation, release, delivery, incident, evidence, and
  rollback records with optimistic concurrency and append-only audits.
- Reproducible quality, safety, latency, token, cost, and baseline-regression gates.
- Privacy-safe OpenTelemetry traces and metrics, SLOs, burn alerts, dashboards, and local
  Collector, Prometheus, Tempo, and Grafana configuration.
- Runtime policy enforcement, PII redaction, rate/token/cost budgets, bounded retries, and
  fail-closed provider behavior.
- Shadow comparisons, guarded canary stages, atomic traffic allocation, and explainable
  cost-aware model selection.
- Evidence-cited incident investigation, policy-bound known-good rollback, and fixed-window
  recovery verification.
- Reproducible Azure reference infrastructure, Helm packaging, workload-identity adapters,
  post-deploy verification, and immutable CI/CD provenance.
- One-command deterministic demo, operator consoles, screenshots, full walkthrough, threat
  model, architecture/API references, ADRs, troubleshooting, and operational runbooks.

### Hardened

- Closed high-risk gateway bypass and rollback-input trust findings; documented remaining
  operator and deployment-boundary risks.
- Added database pool limits, graceful draining and shutdown budgets, migration verification,
  backup/restore guidance, load evidence, failure injection, accessibility states, clean-wheel
  installation, documentation smoke tests, and complete release-to-recovery E2E coverage.

### Boundaries

- The local demo uses only synthetic evidence and deterministic providers.
- Azure resources are never provisioned by setup or CI; applying the reference infrastructure
  is an explicit, potentially billable operator action.
