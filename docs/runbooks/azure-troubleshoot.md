# Azure deployment troubleshooting

Start with the smallest failing boundary. Preserve correlation IDs, safe error types, pod names,
deployment revision, image digest, and timestamps. Do not collect prompts, response bodies,
tokens, connection strings, pod environments, or Secret values.

## Migration hook fails

```bash
kubectl -n agenthub get job,pod -l app.kubernetes.io/component=migration
kubectl -n agenthub logs job/agenthub-migrate
kubectl -n agenthub describe pod -l app.kubernetes.io/component=migration
```

Verify the pod has the `azure.workload.identity/use=true` label, uses the
`agenthub-database-bootstrap` service account, and that its annotation matches Terraform's
database-bootstrap client ID. Confirm private DNS resolves the PostgreSQL FQDN from AKS and TCP
5432 is allowed from the AKS subnet. A principal-creation function error usually means the job is
not connecting to the `postgres` database as the configured Entra administrator.

The hook is idempotent. Correct the cause and rerun the same `helm upgrade --install`; do not
enable password auth or grant the API identity PostgreSQL administrator rights.

## API pod cannot start or become ready

```bash
kubectl -n agenthub describe pod -l app.kubernetes.io/component=api
kubectl -n agenthub get events --sort-by=.lastTimestamp
kubectl -n agenthub logs deployment/agenthub --tail=100
```

- `ImagePullBackOff`: confirm the digest exists in ACR and the AKS kubelet identity has `AcrPull`.
- Secret mount failure: confirm both Key Vault object names exist, the vault permits the AKS
  subnet, and the workload identity has `Key Vault Secrets User`.
- Database readiness failure: confirm the Key Vault database URL names the workload identity, uses
  the private FQDN, selects `agenthub`, and includes `sslmode=require`. Check the migration Job
  first.
- Configuration failure: compare the selected Azure provider fields with the Terraform outputs and
  the approved model deployment. Values are never allowed to fall back silently.

## Workload identity returns 401 or 403

Compare all four coordinates: pod label, service-account annotation, Terraform federated subject,
and managed-identity client ID. The subjects must be exactly:

- `system:serviceaccount:agenthub:agenthub` for the API;
- `system:serviceaccount:agenthub:agenthub-database-bootstrap` for migrations.

Allow for Azure role-assignment propagation after a first apply. Do not replace the bounded roles
with `Owner` or broad `Contributor` access to make a test pass.

## Azure OpenAI fails

Confirm the account resource ID used at plan time matches the endpoint, the named deployment
exists in that account, regional quota is available, and the workload has `Cognitive Services
OpenAI User`. A model name is not necessarily the deployment name. Review token and request quota
before rerunning the smoke suite.

## Azure AI Search fails or returns no grounding

Confirm the service firewall includes the static AKS egress IP and local key authentication remains
disabled. The workload needs `Search Index Data Reader`. Confirm the index schema and the committed
`retail-products-policies` / `v1` documents match
[the adapter contract](../azure/provider-adapters.md#search-index-contract). Index creation and
document writes must use a separate short-lived bootstrap identity.

## Azure Monitor has no application telemetry

Confirm `AGENTHUB_OTEL_EXPORTER` is `azure-monitor`, both runtime values mounted from Key Vault, and
the workload identity has `Monitoring Metrics Publisher` on Application Insights. Run one smoke
request, wait for ingestion latency, then search by service name `agenthub-api` and the smoke
timestamp. Export failures are isolated from requests, so a healthy API does not prove telemetry
delivery.

## Escalation record

Capture the failing boundary, first/last occurrence, safe Azure resource IDs, image digest,
Terraform plan revision, Helm revision, sanitized error class, and attempted remediation. If the
issue risks unexpected spend, follow [Azure cost control](azure-cost-control.md) immediately.
