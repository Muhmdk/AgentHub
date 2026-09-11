# AgentHub Helm chart

This chart packages the existing AgentHub API, its inventory/knowledge/shopping endpoints, a
gateway-facing ClusterIP Service, and a pre-install/pre-upgrade migration Job.

Local rendering uses the offline fake model and in-memory retriever:

```console
helm upgrade --install agenthub deploy/helm/agenthub \
  --namespace agenthub --create-namespace \
  --values deploy/helm/agenthub/values-local.yaml
```

The local profile expects a PostgreSQL Service named `postgres` in the release namespace and
creates a Secret containing only the disposable local credential.

The dev profile selects Azure OpenAI, Azure AI Search, OpenTelemetry, workload identity settings,
and an externally managed `agenthub-runtime` Secret. Supply deployment-specific values at
install time; do not commit them:

```console
helm upgrade --install agenthub deploy/helm/agenthub \
  --namespace agenthub --create-namespace \
  --values deploy/helm/agenthub/values-dev.yaml \
  --set-string image.repository="<registry>.azurecr.io/agenthub" \
  --set-string image.digest="sha256:<64-hex-digest>" \
  --set-string runtime.azureManagedIdentityClientId="<client-id>" \
  --set-string runtime.azureDatabaseBootstrapIdentityClientId="<bootstrap-client-id>" \
  --set-string runtime.azureOpenAIEndpoint="https://<account>.openai.azure.com" \
  --set-string runtime.azureOpenAIDeployment="<deployment>" \
  --set-string runtime.azureSearchEndpoint="https://<service>.search.windows.net" \
  --set-string runtime.azureSearchIndexName="agenthub-chunks-v1" \
  --set-string migrations.databaseUrl="postgresql+psycopg://<bootstrap-identity>@<server>.postgres.database.azure.com:5432/agenthub?sslmode=require" \
  --set-string migrations.appPrincipalName="<workload-identity-name>" \
  --set-string migrations.appPrincipalObjectId="<workload-principal-object-id>" \
  --set-string keyVault.name="<vault-name>" \
  --set-string keyVault.tenantId="<tenant-id>"
```

Dev does not render credentials. The Secrets Store CSI driver mounts the selected Key Vault
objects and syncs the passwordless application database URL and Azure Monitor routing string to
the `agenthub-runtime` Secret consumed by the API. The same secret supplies the JSON
identity-to-token map used by the authenticated gateway; no token appears in chart values or the
runtime ConfigMap. The dev profile enables the digest-pinned OPA sidecar and points the API at its
loopback decision endpoint. The pre-install migration hook uses its separate annotated service
account, obtains a short-lived PostgreSQL token, creates the non-admin workload role, applies
Alembic migrations, and grants only application DML access. The application obtains a fresh token
for every new pooled connection. Both service accounts exactly match the Terraform workload
identity subjects.

The dev profile sends traces and metrics directly to Azure Monitor through managed identity. The
local profile retains the vendor-neutral OTLP/HTTP exporter and local Collector. Index creation and
document ingestion remain a separately privileged operation; the API identity has Search read
access only. Follow the complete [Azure deployment runbook](../../../docs/runbooks/azure-deploy.md).

The default security profile runs both containers as UID/GID 65532 with a read-only root
filesystem, all Linux capabilities dropped, `RuntimeDefault` seccomp, bounded `/tmp` storage,
requests and limits, and startup/liveness/readiness probes. The default-deny NetworkPolicy permits
only same-namespace ingress, DNS, HTTPS provider calls, OTLP in the namespace, and PostgreSQL on
the configured CIDRs.

The dev HPA scales from one to at most two replicas at 70% requested CPU, adds only one pod per
minute, and waits five minutes before scaling down. PDB creation stays disabled for the single-node
dev cluster because a one-replica PDB would block voluntary maintenance without providing
availability. Enable it only after adding another node and maintaining at least two replicas.
Runtime rate, token, and cost windows are process-local, so two replicas each enforce one copy of
the configured limit. Keep one replica when a strict deployment-wide ceiling is required; a
shared atomic budget backend is required before treating a scaled deployment as one global budget.
