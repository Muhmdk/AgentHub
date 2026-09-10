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
  --set-string runtime.azureOpenAIEndpoint="https://<account>.openai.azure.com" \
  --set-string runtime.azureOpenAIDeployment="<deployment>" \
  --set-string runtime.azureSearchEndpoint="https://<service>.search.windows.net" \
  --set-string runtime.azureSearchIndexName="agenthub-chunks-v1"
```

Dev does not render credential values. The referenced Secret is a temporary compatibility
boundary for the database URL; the hardened AKS profile replaces secret material delivery with
the Key Vault CSI/workload identity integration in the next chart checkpoint.
