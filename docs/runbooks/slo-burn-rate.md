# SLO burn-rate response

Use this runbook for `AgentHubAvailabilityFastBurn` or `AgentHubAvailabilitySlowBurn`.

## Triage

1. Open **AgentHub Fleet Health** in Grafana and identify the affected `agent_name`.
2. Open **AgentHub Agent Detail**, select that agent, and compare request, error, p95 latency,
   tool success, evaluation, and cost signals.
3. Open `http://127.0.0.1:8000/observability`, follow the latest trace, and locate the first span
   with an error status. Use the correlation and release attributes to match application logs.
4. Confirm whether the fast-burn pair (5 minutes and 1 hour) or slow-burn pair (30 minutes and
   6 hours) is active. Do not page on a single-window spike.

## Mitigate

- For a release-localized regression, stop further promotion and use the lifecycle rollback path.
- For tool or retrieval failures, disable the affected integration or reduce traffic through the
  normal deployment controls; do not bypass policy checks.
- For provider failures, preserve bounded timeouts and allow safe error or abstention behavior.
- Record the affected release ID, trace ID, start time, user impact, and mitigation owner.

## Resolve

The incident is stable when both burn windows are below their thresholds and the underlying error
ratio has recovered. Preserve traces and evaluation artifacts needed for review. Add a regression
test for the failure mode before closing the incident.

If the dashboards have no data or the Collector target is down, switch to the
[telemetry backend runbook](telemetry-backend.md).
