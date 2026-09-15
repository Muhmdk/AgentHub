# Stuck canary and missing telemetry recovery

Use this runbook when a canary cannot advance, has stale/missing paired observations,
remains paused unexpectedly, or conflicts with a newer route revision. Promotion is
fail-closed; lack of evidence is not evidence of health.

## Triage

1. Read `/delivery/canaries/{id}`, its event list, the referenced route and route events.
   Record both current revisions, stable/candidate release IDs, current traffic weight,
   last gate reasons, and correlation ID.
2. Confirm the candidate and stable IDs in telemetry exactly match the rollout and that the
   comparison window is fresh, long enough, and contains the minimum successful paired
   samples.
3. Inspect policy, database, provider, and telemetry health. Follow the specific outage
   runbook instead of changing guardrail thresholds during an incident.

## Choose a safe action

- **Evidence still collecting:** leave the state unchanged and wait for a complete bounded
  window. Do not repeatedly submit promotion actions.
- **Operator pause:** use `resume` with the latest rollout and route revisions only after the
  original reason is resolved and fresh guardrails pass.
- **Candidate regression or uncertain telemetry:** use `abort`. This atomically sets candidate
  traffic to zero and records the action; it does not erase the candidate or evidence.
- **Revision conflict:** reread route and rollout. If another accepted action already achieved
  the intent, stop. Otherwise issue a new idempotency key against the current revisions.
- **Route no longer matches rollout:** do not force a transition. Escalate ownership and create
  a new candidate/rollout through the normal workflow.

Example abort body (replace identifiers and revisions from current reads):

```json
{
  "idempotency_key": "incident-123-canary-abort-1",
  "action": "abort",
  "expected_revision": 2,
  "expected_route_revision": 2,
  "actor": "service/delivery-controller",
  "reason": "Paired latency guardrail regressed; incident INC-123",
  "telemetry_healthy": false
}
```

Submit it to `POST /delivery/canaries/{id}/actions` through authenticated control-plane
access. Never update route/canary tables directly.

## Verify and close

Confirm the accepted event, intended state, and candidate traffic weight. For abort, verify
stable traffic remains bound to the same immutable known-good release. For resume/promotion,
confirm the returned gate lists every passing sample, freshness, quality, safety, latency,
error, and cost check. Observe the next full window before another stage.

If an incident-triggered rollback was executed but recovery failed, use the
[failed recovery procedure](incident-recovery.md#failed-recovery-and-escalation).
