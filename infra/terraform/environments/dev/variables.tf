variable "subscription_id" {
  description = "Azure subscription for the dev environment."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an Azure UUID."
  }
}

variable "tenant_id" {
  description = "Microsoft Entra tenant used for Azure authentication."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an Azure UUID."
  }
}

variable "location" {
  description = "Azure region for dev resources."
  type        = string
  default     = "canadacentral"
}

variable "project" {
  description = "Short project name used in resource names."
  type        = string
  default     = "agenthub"
}

variable "environment" {
  description = "Explicit environment selector."
  type        = string
  default     = "dev"
}

variable "unique_suffix" {
  description = "Explicit lowercase alphanumeric suffix for global names."
  type        = string
}

variable "owner" {
  description = "Accountable owner tag."
  type        = string
}

variable "github_repository" {
  description = "GitHub owner/repository allowed to request deployment tokens."
  type        = string
  default     = "Muhmdk/AgentHub"
}

variable "github_environment" {
  description = "Protected GitHub environment allowed to deploy."
  type        = string
  default     = "staging"
}

variable "monthly_cost_limit_usd" {
  description = "Reviewed fixed-cost ceiling checked by policy before apply."
  type        = number
  default     = 200

  validation {
    condition     = var.monthly_cost_limit_usd > 0 && var.monthly_cost_limit_usd <= 500
    error_message = "monthly_cost_limit_usd must be greater than zero and no more than 500."
  }
}

variable "budget_contact_emails" {
  description = "Addresses notified as the dev resource-group budget is consumed."
  type        = list(string)

  validation {
    condition     = length(var.budget_contact_emails) > 0 && alltrue([for email in var.budget_contact_emails : can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", email))])
    error_message = "budget_contact_emails must contain at least one valid email address."
  }
}

variable "budget_start_date" {
  description = "First day of the current month in RFC3339 form for Azure budget tracking."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.budget_start_date))
    error_message = "budget_start_date must be the first day of a month, for example 2026-09-01T00:00:00Z."
  }
}

variable "aks_admin_group_object_ids" {
  description = "Entra group object IDs granted AKS administrator access."
  type        = list(string)

  validation {
    condition     = length(var.aks_admin_group_object_ids) > 0 && alltrue([for object_id in var.aks_admin_group_object_ids : can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", object_id))])
    error_message = "aks_admin_group_object_ids must contain at least one Azure UUID."
  }
}

variable "aks_api_authorized_ip_ranges" {
  description = "Operator CIDRs allowed to contact the public dev AKS API."
  type        = set(string)

  validation {
    condition     = length(var.aks_api_authorized_ip_ranges) > 0 && !contains(var.aks_api_authorized_ip_ranges, "0.0.0.0/0")
    error_message = "Provide at least one bounded operator CIDR; 0.0.0.0/0 is forbidden."
  }
}

variable "key_vault_operator_ip_rules" {
  description = "Optional operator IPv4 CIDRs permitted by the Key Vault firewall."
  type        = set(string)
  default     = []
}

variable "vnet_cidr" {
  description = "Virtual network address range."
  type        = string
  default     = "10.40.0.0/16"
}

variable "aks_subnet_cidr" {
  description = "AKS node subnet address range."
  type        = string
  default     = "10.40.0.0/20"
}

variable "postgres_subnet_cidr" {
  description = "PostgreSQL delegated subnet address range."
  type        = string
  default     = "10.40.16.0/24"
}

variable "tags" {
  description = "Additional non-sensitive Azure tags."
  type        = map(string)
  default     = {}
}
