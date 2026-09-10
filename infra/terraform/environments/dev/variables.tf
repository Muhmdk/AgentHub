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
