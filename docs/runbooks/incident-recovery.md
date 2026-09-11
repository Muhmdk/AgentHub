# Incident investigation and known-good recovery

Use this runbook when AgentHub opens an operational incident from an SLO burn, quality regression,
error-rate increase, cost anomaly, safety violation, or canary guardrail failure. A rollback is a
mitigation, not proof of recovery: keep the incident open until the fixed verification window passes.

## First response

1. Open `http://127.0.0.1:8000/incidents-console` and select the newest affected incident.
2. Confirm the agent, environment, release, route, canary, trigger time, current value, and threshold.
3. Assign an incident commander. For manual production rollback, record the approving operator
   separately from the automation actor.
4. Stop further promotion of the affected candidate. Do not delete releases, routes, canaries,
   evidence, rollback operations, or events.
5. Review missing-source and clock-skew warnings before accepting a probable cause.

The incident database, immutable release provenance, and append-only delivery and rollback events
are authoritative. Dashboard labels and generated prose are supporting views only.

## Evidence standard

Collect at least three relevant, sanitized items. Prefer:

- bounded metrics for request, error, p95 latency, retrieval, tool, model, token, and cost behavior;
- a release event and immutable provenance hash;
- the field-level manifest/config difference;
- trace and sanitized-log references, never raw prompts, credentials, or personal data;
- evaluation changes, Kubernetes events, policy decisions, and relevant prior incidents.

Every stored item has a source reference and content hash. The deterministic timeline reports future
clock skew, contradictions, and missing sources. Every investigator statement must resolve to one of
those stored IDs; an uncited or invented ID invalidates the generated report. The investigator can
recommend `request_rollback`, but it has no deployment tools or direct actuation path.

## Automatic rollback boundary

AgentHub may automatically restore the known-good release only when all of these are true:

- the affected rollout is an active canary;
- a persisted canary guardrail trigger was breached;
- the minimum evidence count is present;
- deterministic analysis supports a non-ambiguous cause;
- no concurrent rollout conflicts with the route;
- evidence does not mark a data migration or high-risk change;
- the incident is outside the cooldown and below the maximum attempt count.

The default policy requires three evidence items, a 15-minute cooldown, and at most three attempts.
The API derives these facts from persisted state. A client cannot supply its own evidence count,
guardrail result, canary state, or risk flags. Idempotent retries return the original operation;
reusing a retry key for different content is rejected.

Stable-production rollback, a non-guardrail incident, an ambiguous cause, a data migration, or a
high-risk change requires explicit human approval. Approval cannot override insufficient evidence,
an active cooldown, an exhausted attempt limit, or a concurrent rollout.

## Request a known-good rollback

The incident console's **Approve / request known-good rollback** action uses the incident revision
currently on screen. The equivalent API request contains operator intent only:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/incidents/INCIDENT_ID/rollback \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: incident-recovery-1' \
  -d '{
    "idempotency_key": "incident-recovery-1",
    "expected_incident_revision": 1,
    "actor": "on-call-operator",
    "reason": "Restore the immutable known-good production release",
    "human_approved": true
  }'
```

Fetch the incident again after a stale-revision conflict. Do not add policy facts to the payload or
bypass the endpoint with `kubectl`, Helm, Terraform, or a direct database update.

Before execution, AgentHub revalidates the incident, exact route and canary revisions, target release
ID, provenance hash, production state, release gates, and stable/candidate lineage. Canary recovery
uses the audited abort transition and atomically restores candidate traffic to zero. The command
hash is revalidated immediately before actuation.

## Verify recovery

After execution, place the operation in `verifying` and evaluate one fixed five-minute observation
window. The default recovery policy requires:

| Check | Default |
|---|---:|
| Complete observation window | 300 seconds |
| Observation count | at least 5 |
| Availability | at least 99% |
| Error rate | at most 1% |
| Agent p95 latency | at most 1000 ms |
| Guardrail state | healthy |
| Required telemetry | complete |

An early evaluation remains `pending`; it cannot close the incident. When every check passes, the
rollback becomes `recovered` and the incident becomes `resolved`. Missing telemetry or any failed
check after the deadline makes the rollback and incident `escalated`.

Confirm the complete append-only sequence:

```text
rollback: requested → executed → verifying → recovered | escalated
canary:   created → active stage → rolled_back
route:    candidate traffic > 0 → candidate traffic = 0
incident: detected → verifying → resolved | escalated
```

## Failed recovery and escalation

If recovery fails, keep traffic on the validated known-good allocation and page the incident owner.
Record the failed checks, telemetry sources, route revision, release provenance hash, attempt count,
and next diagnostic owner. Do not retry during cooldown or exceed the attempt limit.

Treat these cases as manual escalation:

- telemetry is absent, stale, contradictory, or outside the fixed window;
- the stable release is also unhealthy;
- a migration or external state change cannot be safely reversed;
- multiple rollouts or incidents affect the same route;
- safety or governance evidence suggests broader impact;
- the known-good artifact or provenance cannot be verified.

Continue with the [SLO burn-rate runbook](slo-burn-rate.md) for budget exhaustion, the
[telemetry backend runbook](telemetry-backend.md) for missing signals, or the
[governance emergency runbook](governance-emergency.md) for policy/safety impact.

## Reproduce the canonical drill

The deterministic injector demonstrates `top_k: 5 → 50`. Retrieval p95 rises from 95 ms to 500 ms,
model p95 remains 200 ms, and agent p95 rises from 295 ms to 700 ms.

```bash
make demo-incident-fault
.venv/bin/pytest tests/e2e/test_incident_rollback.py --no-cov
```

Set `AGENTHUB_DATABASE_URL` in the shell before running the E2E command. Use only the dedicated
local/test database: its fixture truncates AgentHub tables before and after the drill. The test
proves trigger detection, evidence correlation, citation grounding, automatic policy eligibility,
immutable known-good rollback, audit ordering, recovery, and incident resolution without cloud
credentials.
