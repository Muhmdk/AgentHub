# AgentHub Terraform

The Terraform configuration has two state boundaries:

- `bootstrap` creates the versioned, RBAC-protected Azure Blob backend;
- `environments/dev` creates the application environment and uses a distinct state key.

No state, plan, backend configuration, or real variable file belongs in Git. Example files contain
only placeholders. Commands below authenticate with the operator's Azure CLI session; CI later
uses the GitHub environment's federated deployment identity.

## Bootstrap remote state

Copy `bootstrap/terraform.tfvars.example` to `bootstrap/terraform.tfvars`, replace every
placeholder, and include the applying operator's Entra object ID in
`state_principal_object_ids`. The first init intentionally disables the not-yet-created backend:

```bash
cd infra/terraform/bootstrap
terraform init -backend=false
terraform plan -out bootstrap.tfplan
terraform apply bootstrap.tfplan
cp backend.hcl.example backend.hcl
terraform init -migrate-state -backend-config=backend.hcl
```

After the environment creates its deployment identity, add that identity's object ID to the
bootstrap principals and apply the bootstrap state again. This grants GitHub's short-lived
identity data-plane access without a storage key.

## Plan the dev environment

Copy both example files in `environments/dev`, replace their placeholders, then initialize and
create a saved plan. Planning or applying billable resources is never an automatic PR action.

```bash
cd infra/terraform/environments/dev
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive ../../
terraform validate
terraform plan -out dev.tfplan
terraform show -json dev.tfplan > dev.tfplan.json
```

Review the human-readable plan, the policy result, and the refreshed cost estimate before an
operator runs `terraform apply dev.tfplan`. See
[`docs/azure/architecture-and-cost.md`](../../../docs/azure/architecture-and-cost.md) for the
approved inventory, threat boundary, and monthly ceiling.

## Offline validation

Install Terraform 1.16.2, Helm 4.2.4, and kubeconform 0.8.0, then run:

```bash
make infra-validate
```

The command validates both Terraform state roots, runs the mock-provider module plans, lints the
chart and both values profiles, checks rendered built-in Kubernetes resources against their
schemas, and enforces the dev security contract. The pull-request infrastructure workflow
downloads those exact CLI versions with pinned SHA-256 checksums and runs the same targets. It
does not authenticate to Azure, run a live plan, or apply resources.
