# AgentHub Helm chart

This chart packages the existing AgentHub API, its inventory/knowledge/shopping endpoints, a
gateway-facing ClusterIP Service, and an Alembic post-install/post-upgrade migration Job.

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
  --set-string keyVault.name="<vault-name>" \
  --set-string keyVault.tenantId="<tenant-id>"
```

Dev does not render credential values. The Secrets Store CSI driver mounts the selected Key Vault
objects and syncs the database URL to the `agenthub-runtime` Secret consumed by the API and
migration job. The application and migration job use separate annotated service accounts matching
the Terraform workload identity subjects.

The default security profile runs both containers as UID/GID 65532 with a read-only root
filesystem, all Linux capabilities dropped, `RuntimeDefault` seccomp, bounded `/tmp` storage,
requests and limits, and startup/liveness/readiness probes. The default-deny NetworkPolicy permits
only same-namespace ingress, DNS, HTTPS provider calls, OTLP in the namespace, and PostgreSQL on
the configured CIDRs.

The dev HPA scales from one to at most two replicas at 70% requested CPU, adds only one pod per
minute, and waits five minutes before scaling down. PDB creation stays disabled for the single-node
dev cluster because a one-replica PDB would block voluntary maintenance without providing
availability. Enable it only after adding another node and maintaining at least two replicas.
