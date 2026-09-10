# Azure development deployment

Use this runbook to create the reviewed `dev` environment and install AgentHub. Every `apply`,
image build, model request, and Search request can incur Azure charges. CI validates the
configuration but never provisions resources.

## Preconditions

- Azure CLI is signed in to the intended tenant and subscription.
- Terraform 1.16.2, Helm 4.2.4, `kubectl`, `kubelogin`, `jq`, and the repository Python toolchain
  are installed.
- The applying principal can create resource groups, role assignments, managed identities, and
  the state storage boundary.
- The AKS administrator group, operator public CIDRs, budget recipients, unique suffix, and
  monthly ceiling have been reviewed.
- An existing quota-approved Azure OpenAI or Foundry deployment is available. Its account ID is
  supplied to Terraform so the workload receives inference-only access.
- A member of an approved operator group can create the documented Search index and upload the
  committed `retail-products-policies` corpus from a reviewed operator CIDR. See
  [the Search index contract](../azure/provider-adapters.md#search-index-contract).

Do not place IDs, backend coordinates, plans, state, connection strings, or generated values files
in Git.

## 1. Validate without Azure access

From the repository root:

```bash
make setup
make infra-validate
```

This must pass before a live plan is created.

## 2. Bootstrap remote state

Copy the two bootstrap examples to ignored local files and replace every placeholder:

```bash
cd infra/terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
terraform init -backend=false
terraform plan -out bootstrap.tfplan
terraform show bootstrap.tfplan
terraform apply bootstrap.tfplan
terraform init -migrate-state -backend-config=backend.hcl
```

After the environment creates the GitHub deployment identity, add its principal object ID to
`state_principal_object_ids`, plan the bootstrap root again, review it, and apply it. This grants
state data-plane access without a storage key.

## 3. Review and apply the environment plan

Copy the ignored environment examples and replace every placeholder. The budget start date must
be the first day of the current month, and neither operator CIDR may be `0.0.0.0/0`.

```bash
cd ../environments/dev
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive ../../
terraform validate
terraform plan -out dev.tfplan
terraform show dev.tfplan
terraform show -json dev.tfplan > dev.tfplan.json
```

Confirm the plan matches [the approved inventory and cost ceiling](../azure/architecture-and-cost.md),
contains no secret values, and is attached to the pull request as a protected artifact. Only then:

```bash
terraform apply dev.tfplan
terraform plan -detailed-exitcode
```

The second command must exit `0`. Exit `2` means drift remains and must be reviewed; exit `1`
means planning failed.

## 4. Prepare the image and runtime coordinates

Export non-secret deployment values from Terraform without printing any secret:

```bash
TF_OUTPUT=$(terraform output -json)
RESOURCE_GROUP=$(jq -r '.foundation.value.resource_group.name' <<<"$TF_OUTPUT")
ACR_NAME=$(jq -r '.foundation.value.container_registry.name' <<<"$TF_OUTPUT")
ACR_LOGIN=$(jq -r '.foundation.value.container_registry.login_server' <<<"$TF_OUTPUT")
AKS_NAME=$(jq -r '.platform.value.aks.name' <<<"$TF_OUTPUT")
KEY_VAULT_NAME=$(jq -r '.platform.value.key_vault.name' <<<"$TF_OUTPUT")
POSTGRES_FQDN=$(jq -r '.platform.value.postgres.fqdn' <<<"$TF_OUTPUT")
WORKLOAD_NAME=$(jq -r '.foundation.value.workload_identity.name' <<<"$TF_OUTPUT")
WORKLOAD_CLIENT_ID=$(jq -r '.foundation.value.workload_identity.client_id' <<<"$TF_OUTPUT")
WORKLOAD_OBJECT_ID=$(jq -r '.foundation.value.workload_identity.principal_id' <<<"$TF_OUTPUT")
DB_BOOTSTRAP_NAME=$(jq -r '.platform.value.database_bootstrap_identity.name' <<<"$TF_OUTPUT")
DB_BOOTSTRAP_CLIENT_ID=$(jq -r '.platform.value.database_bootstrap_identity.client_id' <<<"$TF_OUTPUT")
SEARCH_ENDPOINT=$(jq -r '.platform.value.search.endpoint' <<<"$TF_OUTPUT")
APPI_ID=$(jq -r '.platform.value.monitor.application_insights_id' <<<"$TF_OUTPUT")
APPI_NAME=${APPI_ID##*/}
TENANT_ID=$(az account show --query tenantId --output tsv)
```

Build an immutable image from the reviewed commit, then resolve its registry digest:

```bash
SOURCE_SHA=$(git rev-parse HEAD)
az acr build --registry "$ACR_NAME" --image "agenthub:$SOURCE_SHA" --file Dockerfile .
IMAGE_DIGEST=$(az acr manifest show-metadata \
  --registry "$ACR_NAME" \
  --name "agenthub:$SOURCE_SHA" \
  --query digest --output tsv)
test -n "$IMAGE_DIGEST"
```

## 5. Provision the two runtime values

The PostgreSQL URLs contain identity names but no password. The API receives a fresh Entra token
for every new pooled connection. The migration job uses the separate Entra administrator only
while creating the workload role and applying migrations.

```bash
APPLICATION_DATABASE_URL="postgresql+psycopg://$WORKLOAD_NAME@$POSTGRES_FQDN:5432/agenthub?sslmode=require"
MIGRATION_DATABASE_URL="postgresql+psycopg://$DB_BOOTSTRAP_NAME@$POSTGRES_FQDN:5432/agenthub?sslmode=require"
MONITOR_CONNECTION_STRING=$(az monitor app-insights component show \
  --resource-group "$RESOURCE_GROUP" \
  --app "$APPI_NAME" \
  --query connectionString --output tsv)

az keyvault secret set --vault-name "$KEY_VAULT_NAME" \
  --name database-url --value "$APPLICATION_DATABASE_URL" --output none
az keyvault secret set --vault-name "$KEY_VAULT_NAME" \
  --name azure-monitor-connection-string \
  --value "$MONITOR_CONNECTION_STRING" --output none
unset MONITOR_CONNECTION_STRING
```

Run these commands only from an approved Key Vault operator CIDR as a member of one of the
configured operator groups. Never print either Key Vault value in CI logs.

## 6. Configure Kubernetes and install Helm

Use Entra credentials; the cluster has no local administrator account:

```bash
az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$AKS_NAME" --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
kubectl create namespace agenthub --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace agenthub \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted --overwrite
```

Replace the model endpoint and deployment with the approved existing deployment. The Search index
name must match the separately created and populated index.

```bash
helm upgrade --install agenthub deploy/helm/agenthub \
  --namespace agenthub \
  --values deploy/helm/agenthub/values-dev.yaml \
  --atomic --wait --timeout 15m \
  --set-string image.repository="$ACR_LOGIN/agenthub" \
  --set-string image.digest="$IMAGE_DIGEST" \
  --set-string runtime.azureManagedIdentityClientId="$WORKLOAD_CLIENT_ID" \
  --set-string runtime.azureDatabaseBootstrapIdentityClientId="$DB_BOOTSTRAP_CLIENT_ID" \
  --set-string runtime.azureOpenAIEndpoint="https://MODEL_ACCOUNT.openai.azure.com" \
  --set-string runtime.azureOpenAIDeployment="APPROVED_DEPLOYMENT" \
  --set-string runtime.azureSearchEndpoint="$SEARCH_ENDPOINT" \
  --set-string runtime.azureSearchIndexName="agenthub-chunks-v1" \
  --set-string migrations.databaseUrl="$MIGRATION_DATABASE_URL" \
  --set-string migrations.appPrincipalName="$WORKLOAD_NAME" \
  --set-string migrations.appPrincipalObjectId="$WORKLOAD_OBJECT_ID" \
  --set-string keyVault.name="$KEY_VAULT_NAME" \
  --set-string keyVault.tenantId="$TENANT_ID"
```

The pre-install hook uses the database-bootstrap service account, creates or reuses the workload
Entra role, runs Alembic, and grants only connection and DML privileges. Continue with the
[verification runbook](azure-verify.md).
