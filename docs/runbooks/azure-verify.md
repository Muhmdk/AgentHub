# Azure deployment verification

Use this runbook after every infrastructure apply or Helm upgrade and before directing traffic to
the deployment.

## Infrastructure convergence

From `infra/terraform/environments/dev`:

```bash
terraform plan -detailed-exitcode
```

Exit `0` is required. Retain the reviewed plan artifact with the pull request. Do not attach the
state file, backend file, generated variable file, or any command output containing Key Vault
values.

## Kubernetes health and security

```bash
kubectl -n agenthub rollout status deployment/agenthub --timeout=5m
kubectl -n agenthub get deployment,service,hpa,networkpolicy,secretproviderclass
kubectl -n agenthub get pods -o wide
kubectl -n agenthub logs job/agenthub-migrate
kubectl -n agenthub get pod -l app.kubernetes.io/component=api \
  -o jsonpath='{range .items[*]}{.metadata.name}{" runAsNonRoot="}{.spec.securityContext.runAsNonRoot}{" image="}{.spec.containers[0].image}{"\n"}{end}'
```

Require one ready API pod, an image reference containing `@sha256:`, successful migration output,
the restricted namespace labels, and no warning events. Do not dump pod environments or Kubernetes
Secrets.

## Functional smoke suite

Port-forward the ClusterIP Service from an authorized workstation:

```bash
kubectl -n agenthub port-forward service/agenthub-gateway 8080:80
```

In a second terminal:

```bash
make smoke-deployment \
  BASE_URL=http://127.0.0.1:8080 \
  SMOKE_ARGS="--expected-model-prefix azure-openai/ --environment azure-smoke"
```

The command must exit `0` and report `evaluation_gate_passed: true`. It checks liveness,
readiness, version, immutable registration, inventory tools, an Azure Search-grounded knowledge
answer, and the inventory evaluation suite. It makes four bounded model calls in the normal path.

## Azure evidence

In Application Insights, query the last 15 minutes and confirm `agenthub-api` traces and metrics
arrived after the smoke run. In Azure AI Search, confirm query metrics increased for the selected
index. In PostgreSQL, confirm the API readiness check succeeds without enabling password auth.

Finally confirm:

- the workload identity has only Key Vault read, Search query, model inference, and Monitor publish
  roles;
- the migration identity is the PostgreSQL Entra administrator and is not used by the API pod;
- the Kubernetes Service remains `ClusterIP` unless a separately reviewed ingress is installed;
- no credential, connection string, state, plan, kubeconfig, or rendered secret is present in Git.

For failures, use [Azure deployment troubleshooting](azure-troubleshoot.md).
