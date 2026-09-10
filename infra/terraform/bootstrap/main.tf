locals {
  tags = {
    application = "agenthub"
    environment = "shared"
    managed-by  = "terraform"
    owner       = var.owner
    purpose     = "terraform-state"
  }
}

resource "azurerm_resource_group" "state" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "state" {
  name                              = var.storage_account_name
  resource_group_name               = azurerm_resource_group.state.name
  location                          = azurerm_resource_group.state.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  account_kind                      = "StorageV2"
  access_tier                       = "Hot"
  allow_nested_items_to_be_public   = false
  shared_access_key_enabled         = false
  public_network_access_enabled     = true
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }
}

resource "azurerm_storage_container" "state" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "state_blob_contributor" {
  for_each = var.state_principal_object_ids

  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}
