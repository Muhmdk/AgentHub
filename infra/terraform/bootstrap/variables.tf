variable "subscription_id" {
  description = "Azure subscription that owns the Terraform state resources."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an Azure UUID."
  }
}

variable "tenant_id" {
  description = "Microsoft Entra tenant used for Azure authentication."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an Azure UUID."
  }
}

variable "location" {
  description = "Azure region for state resources."
  type        = string
  default     = "canadacentral"
  nullable    = false
}

variable "resource_group_name" {
  description = "Dedicated resource group for Terraform state."
  type        = string
  nullable    = false

  validation {
    condition     = length(var.resource_group_name) >= 1 && length(var.resource_group_name) <= 90
    error_message = "resource_group_name must contain 1 to 90 characters."
  }
}

variable "storage_account_name" {
  description = "Globally unique storage account name using 3-24 lowercase alphanumeric characters."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_name must contain 3-24 lowercase letters or digits."
  }
}

variable "container_name" {
  description = "Private blob container used for Terraform state objects."
  type        = string
  default     = "tfstate"
  nullable    = false

  validation {
    condition     = length(var.container_name) >= 3 && length(var.container_name) <= 63 && can(regex("^[a-z0-9](?:[a-z0-9-]*[a-z0-9])$", var.container_name))
    error_message = "container_name must be a valid 3-63 character blob container name."
  }
}

variable "owner" {
  description = "Accountable owner recorded on all state resources."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.owner)) > 0
    error_message = "owner must not be empty."
  }
}

variable "state_principal_object_ids" {
  description = "Entra object IDs allowed to read and write Terraform state through Azure RBAC."
  type        = set(string)
  nullable    = false

  validation {
    condition = length(var.state_principal_object_ids) > 0 && alltrue([
      for object_id in var.state_principal_object_ids : can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", object_id))
    ])
    error_message = "Every state principal object ID must be an Azure UUID."
  }
}
