# Azure development cost control

Use this runbook before every apply, weekly while the environment exists, and immediately after a
cost alert. The approved fixed planning ceiling is USD 200/month before model usage. The current
detailed estimate and exclusions are in
[Azure architecture and cost bounds](../azure/architecture-and-cost.md#monthly-development-estimate).

## Before apply

1. Refresh the listed Canada Central retail meters and record the retrieval date.
2. Recalculate each monthly amount as hourly rate × 730, daily rate × 30.4, or unit rate × planned
   usage. Keep model tokens, egress, builds, and telemetry overage separate from the fixed total.
3. Confirm the Terraform plan retains one Free-tier AKS control plane, one
   `Standard_D2as_v5` node, Basic ACR, `B_Standard_B1ms` PostgreSQL, Basic Search, 32 GiB database
   storage, and a 0.15 GB/day Log Analytics cap.
4. Reject the apply if the refreshed fixed total exceeds the approved ceiling or the plan adds an
   unpriced resource.
5. Confirm budget notifications have at least one current recipient.

The Azure budget alerts at 50%, 75%, 90%, and 100%; it does not stop resources automatically.

## Weekly review

Open Azure Cost Management at the dev resource-group scope, select month-to-date actual and
forecast cost, and group by service name. Filter or verify the mandatory tags:

- `application=agenthub`
- `environment=dev`
- `managed-by=terraform`
- the reviewed `owner` value

Compare actuals with the elapsed-month share of the estimate. Also review Azure OpenAI token usage,
Search units, Log Analytics ingestion, ACR storage/builds, public egress, PostgreSQL storage growth,
and orphaned managed disks or public IPs.

## Alert response

- At 50%: validate attribution and forecast; stop demos and repeated smoke runs if usage is early.
- At 75%: pause nonessential builds/model calls and schedule teardown after the active review.
- At 90%: obtain explicit approval for any further paid use or tear down the environment.
- At 100%: stop new usage immediately and begin the teardown runbook. Treat the budget as an alert,
  not a spending hard stop.

AKS's system pool cannot be the basis of a reliable zero-cost pause, and Basic Search continues to
bill while it exists. For more than a short idle window, use
[the complete teardown](azure-teardown.md). Never delete individual Terraform-managed resources
from the portal as a cost-control shortcut; that creates drift and can leave chargeable
dependencies behind.
