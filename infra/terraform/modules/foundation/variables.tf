variable "project" {
  description = "Short lowercase project name used in Azure resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.project))
    error_message = "project must be 2-16 lowercase letters, digits, or hyphens and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string

  validation {
    condition     = contains(["dev"], var.environment)
    error_message = "Only the reviewed dev environment is supported in this phase."
  }
}

variable "location" {
  description = "Azure region for environment resources."
  type        = string
}

variable "unique_suffix" {
  description = "Explicit lowercase alphanumeric suffix for globally unique resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{4,8}$", var.unique_suffix))
    error_message = "unique_suffix must contain 4-8 lowercase letters or digits."
  }
}

variable "owner" {
  description = "Accountable owner tag."
  type        = string

  validation {
    condition     = length(trimspace(var.owner)) > 0
    error_message = "owner must not be empty."
  }
}

variable "github_repository" {
  description = "GitHub owner/repository trusted by the deployment identity."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository form."
  }
}

variable "github_environment" {
  description = "Protected GitHub environment trusted by the deployment identity."
  type        = string
}

variable "vnet_cidr" {
  description = "Virtual network address range."
  type        = string
}

variable "aks_subnet_cidr" {
  description = "AKS node subnet address range."
  type        = string
}

variable "postgres_subnet_cidr" {
  description = "PostgreSQL delegated subnet address range."
  type        = string
}

variable "tags" {
  description = "Additional non-sensitive tags. Mandatory tags take precedence."
  type        = map(string)
  default     = {}
}
