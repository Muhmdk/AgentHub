output "aks" {
  description = "AKS identity and endpoint metadata; kubeconfig is intentionally excluded."
  value = {
    id                = azurerm_kubernetes_cluster.environment.id
    name              = azurerm_kubernetes_cluster.environment.name
    resource_group    = azurerm_kubernetes_cluster.environment.resource_group_name
    fqdn              = azurerm_kubernetes_cluster.environment.fqdn
    oidc_issuer_url   = azurerm_kubernetes_cluster.environment.oidc_issuer_url
    egress_ip_address = azurerm_public_ip.aks_egress.ip_address
  }
}

output "database_bootstrap_identity" {
  description = "Identity reserved for the bounded database initialization service account."
  value = {
    name      = azurerm_user_assigned_identity.database_bootstrap.name
    client_id = azurerm_user_assigned_identity.database_bootstrap.client_id
  }
}

output "postgres" {
  description = "Private PostgreSQL endpoint metadata."
  value = {
    id   = azurerm_postgresql_flexible_server.environment.id
    name = azurerm_postgresql_flexible_server.environment.name
    fqdn = azurerm_postgresql_flexible_server.environment.fqdn
  }
}

output "key_vault" {
  description = "Key Vault metadata; secret contents are never outputs."
  value = {
    id   = azurerm_key_vault.environment.id
    name = azurerm_key_vault.environment.name
    uri  = azurerm_key_vault.environment.vault_uri
  }
}

output "search" {
  description = "Azure AI Search endpoint metadata; query keys are intentionally excluded."
  value = {
    id       = azurerm_search_service.environment.id
    name     = azurerm_search_service.environment.name
    endpoint = azurerm_search_service.environment.endpoint
  }
}

output "monitor" {
  description = "Azure Monitor resource IDs; credentials and connection strings are excluded."
  value = {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.environment.id
    application_insights_id    = azurerm_application_insights.environment.id
  }
}
