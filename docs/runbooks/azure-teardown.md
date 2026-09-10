# Azure development teardown

Use this runbook after demonstrations, at the cost threshold, or whenever the dev environment will
be idle. Destruction is irreversible for application data and ACR images. The remote state boundary
is deliberately preserved unless a separate final decision removes it.

## 1. Inventory and protect evidence

From `infra/terraform/environments/dev`, record the commit, reviewed plan, image digest, smoke
result, and any required sanitized incident evidence. Export application data only if retention was
explicitly approved; do not copy tokens, connection strings, or state into the repository.

```bash
terraform state list
OUTPUT_SNAPSHOT=$(mktemp -t agenthub-dev-outputs)
terraform output -json > "$OUTPUT_SNAPSHOT"
kubectl -n agenthub get all
```

The temporary output file contains resource metadata and must be deleted from the workstation after
verification. It must never be committed or attached publicly.

## 2. Remove the workload

```bash
helm uninstall agenthub --namespace agenthub --wait
kubectl delete namespace agenthub --wait=true
```

Deleting the namespace also removes retained Helm hook resources such as the migration service
account and Job.

## 3. Review and apply a destroy plan

```bash
terraform plan -destroy -out dev-destroy.tfplan
terraform show dev-destroy.tfplan
terraform apply dev-destroy.tfplan
```

Confirm the plan targets only the environment state and includes the complete dev resource group,
AKS, public IP, ACR, PostgreSQL, Search, Key Vault, Monitor resources, identities, role assignments,
private DNS, and budget. Never substitute a portal resource-group deletion without reconciling
Terraform state.

## 4. Verify Azure cleanup

```bash
RESOURCE_GROUP=$(jq -r '.foundation.value.resource_group.name' "$OUTPUT_SNAPSHOT")
az group exists --name "$RESOURCE_GROUP"
terraform state list
```

The group check must return `false`, and the environment state must be empty. Review the
subscription for unattached disks, public IPs, snapshots, ACR tasks, and resources carrying the
AgentHub tags.

## Resources intentionally not destroyed

- The separate Terraform state resource group, storage account, container, current state blob,
  historical blob versions, and lock metadata remain.
- A pre-existing Azure OpenAI or Foundry account and model deployment remain because this stack only
  assigns access to them. Remove the model deployment separately if it was created only for this
  project and its owner approves deletion.
- Key Vault has purge protection and seven-day soft-delete retention. Its deleted vault cannot be
  immediately purged; do not attempt to bypass that protection.
- Pull-request plan artifacts and approved operational evidence follow their own retention policy.

Delete the temporary output snapshot after the checks. Destroy the bootstrap root only after all
environment states are empty, required state history is archived in an approved location, and an
explicit reviewer authorizes removal of the recovery boundary.
