output "backend" {
  description = "Non-secret values required by the partial azurerm backend configuration."
  value = {
    resource_group_name  = azurerm_resource_group.state.name
    storage_account_name = azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.state.name
  }
}

output "storage_account_id" {
  description = "Resource ID used to scope state data-plane access."
  value       = azurerm_storage_account.state.id
}
