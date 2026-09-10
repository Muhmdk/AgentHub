variable "tenant_id" {
  description = "Microsoft Entra tenant for AKS, Key Vault, and PostgreSQL authentication."
  type        = string
}

variable "project" {
  description = "Short project name used in Azure resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "unique_suffix" {
  description = "Explicit suffix for globally unique names."
  type        = string
}

variable "owner" {
  description = "Accountable owner tag."
  type        = string
}

variable "resource_group" {
  description = "Foundation resource group."
  type = object({
    id       = string
    name     = string
    location = string
  })
}

variable "virtual_network_id" {
  description = "Foundation virtual network resource ID."
  type        = string
}

variable "aks_subnet_id" {
  description = "Subnet resource ID for AKS nodes."
  type        = string
}

variable "postgres_subnet_id" {
  description = "Delegated subnet resource ID for PostgreSQL."
  type        = string
}

variable "container_registry_id" {
  description = "Container registry resource ID granted to the AKS kubelet identity."
  type        = string
}

variable "aks_identities" {
  description = "Pre-created control-plane and kubelet identities."
  type = object({
    control_plane = object({
      id           = string
      client_id    = string
      principal_id = string
    })
    kubelet = object({
      id           = string
      client_id    = string
      principal_id = string
    })
  })
}

variable "workload_identity" {
  description = "Foundation identity used by AgentHub application pods."
  type = object({
    id           = string
    name         = string
    client_id    = string
    principal_id = string
  })
}

variable "azure_openai_resource_id" {
  description = "Optional existing Azure OpenAI account granted to the workload identity; model deployment remains an explicit quota-aware operation."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.azure_openai_resource_id == null || can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.CognitiveServices/accounts/[^/]+$", var.azure_openai_resource_id))
    error_message = "azure_openai_resource_id must be a complete Cognitive Services account resource ID when set."
  }
}

variable "aks_admin_group_object_ids" {
  description = "Entra group object IDs granted AKS administrator access."
  type        = list(string)
}

variable "aks_api_authorized_ip_ranges" {
  description = "Bounded operator CIDRs allowed to contact the AKS API."
  type        = set(string)
}

variable "key_vault_operator_ip_rules" {
  description = "Operator IPv4 CIDRs allowed by the Key Vault firewall."
  type        = set(string)
  default     = []
}

variable "node_vm_size" {
  description = "Reviewed single-node development VM size."
  type        = string
  default     = "Standard_D2as_v5"
}

variable "log_daily_quota_gb" {
  description = "Hard daily Log Analytics ingestion cap."
  type        = number
  default     = 0.15

  validation {
    condition     = var.log_daily_quota_gb > 0 && var.log_daily_quota_gb <= 0.15
    error_message = "The dev Log Analytics daily quota must be no more than 0.15 GB."
  }
}

variable "monthly_cost_limit_usd" {
  description = "Reviewed monthly resource-group budget."
  type        = number
}

variable "budget_contact_emails" {
  description = "Budget notification recipients."
  type        = list(string)
}

variable "budget_start_date" {
  description = "First day of the current month in RFC3339 form."
  type        = string
}

variable "tags" {
  description = "Additional non-sensitive tags."
  type        = map(string)
  default     = {}
}
