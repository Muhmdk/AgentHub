# Model or retrieval provider outage

Use this runbook when an agent reports a normalized model/retrieval timeout or unavailable
error, availability SLO burn begins, or Azure OpenAI/Azure AI Search health changes. A
provider outage is not permission to bypass policy, extend deadlines without review,
fabricate citations, or silently switch models/indexes.

## Contain

1. Record environment, affected agent/release, correlation and trace IDs, safe error code,
   first/last occurrence, and the provider configured on that immutable release.
2. Pause active canaries and promotions for the affected agent. Do not mutate the stable
   route solely because an external provider is unavailable.
3. If errors correlate with a candidate, follow the
   [incident recovery runbook](incident-recovery.md) and restore the existing known-good
   release through policy. Otherwise preserve the route and return the bounded safe error
   or grounded abstention.
4. Confirm budgets and rate limits have not been exhausted before declaring an outage.

## Diagnose

- Check `/observability/agents/{name}` and the matching trace without searching raw prompt
  content. Separate model, retrieval, tool, policy, and database latency.
- Confirm the configured endpoint, deployment/index name, workload identity, private DNS,
  and network policy against approved Terraform/Helm output. Never print access tokens.
- For Azure OpenAI, check deployment availability, quota/throttling, and identity role.
  For Azure AI Search, check index existence/version, document count, filters, and identity
  role. Continue with [Azure troubleshooting](azure-troubleshoot.md) for commands.
- In local mode, the fake model and local retrieval adapter make no network calls. Treat
  their failure as an application regression and reproduce it with the focused unit test.

## Recover and verify

1. Restore the configured dependency or deploy a reviewed configuration change through the
   normal release workflow. AgentHub has no automatic cross-provider failover.
2. Verify readiness, then run the bounded deployment smoke suite with the expected model
   prefix. Confirm citations reference returned retrieval result IDs.
3. Observe one full SLO window. Resume a paused canary only with fresh paired telemetry and
   passing guardrails.
4. Record provider status, immutable application/policy versions, test output, and the time
   normal traffic resumed. Add a deterministic regression test when the failure was ours.

## Escalate

Escalate immediately for suspected credential compromise, cross-tenant data exposure,
unsafe model output, poisoned retrieval content, or sustained unavailability beyond the
service objective. Rotate or revoke credentials through the owning platform procedure;
do not paste them into the incident record.
