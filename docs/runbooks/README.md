# Operator runbooks

Use the narrowest runbook that matches the observed failure. Preserve correlation IDs,
release/provenance identifiers, sanitized evidence, actions, approvals, and verification
results in the incident record. Never repair control-plane state with direct SQL,
`kubectl edit`, or mutable image tags.

| Condition | Runbook |
| --- | --- |
| Model or retrieval provider unavailable/degraded | [Provider outage](provider-outage.md) |
| Policy service/bundle outage | [Governance emergency](governance-emergency.md) |
| Evaluation, scan, attestation, or promotion failure | [Release failure](release-recovery.md) |
| Missing telemetry or stuck canary | [Canary recovery](canary-recovery.md) |
| SLO/error-budget burn | [SLO burn rate](slo-burn-rate.md) |
| Telemetry export/backend failure | [Telemetry backend](telemetry-backend.md) |
| Incident investigation or failed rollback/recovery | [Incident recovery](incident-recovery.md) |
| Database outage, migration, backup, or restore | [Database recovery](database-recovery.md) |
| Azure deployment failure | [Azure troubleshooting](azure-troubleshoot.md) |
| Azure cost alert | [Azure cost control](azure-cost-control.md) |

Azure creation, verification, and deletion are explicit operator actions documented in
the [deploy](azure-deploy.md), [verify](azure-verify.md), and
[teardown](azure-teardown.md) runbooks. Repository setup and CI never provision or delete
Azure resources.
