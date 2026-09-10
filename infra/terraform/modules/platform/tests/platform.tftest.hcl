mock_provider "azurerm" {
  mock_resource "azurerm_public_ip" {
    defaults = {
      ip_address = "203.0.113.20"
    }
  }
}

variables {
  tenant_id     = "00000000-0000-0000-0000-000000000001"
  project       = "agenthub"
  environment   = "dev"
  unique_suffix = "a1b2"
  owner         = "Muhammad Khan"
  resource_group = {
    id       = "/subscriptions/mock/resourceGroups/rg-agenthub-dev-a1b2"
    name     = "rg-agenthub-dev-a1b2"
    location = "canadacentral"
  }
  virtual_network_id    = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.Network/virtualNetworks/vnet"
  aks_subnet_id         = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.Network/virtualNetworks/vnet/subnets/aks"
  postgres_subnet_id    = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.Network/virtualNetworks/vnet/subnets/postgres"
  container_registry_id = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.ContainerRegistry/registries/acr"
  aks_identities = {
    control_plane = {
      id           = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.ManagedIdentity/userAssignedIdentities/control"
      client_id    = "00000000-0000-0000-0000-000000000020"
      principal_id = "00000000-0000-0000-0000-000000000021"
    }
    kubelet = {
      id           = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
      client_id    = "00000000-0000-0000-0000-000000000022"
      principal_id = "00000000-0000-0000-0000-000000000023"
    }
  }
  workload_identity = {
    id           = "/subscriptions/mock/resourceGroups/mock/providers/Microsoft.ManagedIdentity/userAssignedIdentities/workload"
    name         = "id-workload-agenthub-dev-a1b2"
    client_id    = "00000000-0000-0000-0000-000000000010"
    principal_id = "00000000-0000-0000-0000-000000000011"
  }
  aks_admin_group_object_ids   = ["00000000-0000-0000-0000-000000000012"]
  aks_api_authorized_ip_ranges = ["203.0.113.10/32"]
  monthly_cost_limit_usd       = 200
  budget_contact_emails        = ["owner@example.com"]
  budget_start_date            = "2026-09-01T00:00:00Z"
}

run "plans_secure_development_platform" {
  command = plan

  assert {
    condition     = azurerm_kubernetes_cluster.environment.sku_tier == "Free" && azurerm_kubernetes_cluster.environment.default_node_pool[0].node_count == 1
    error_message = "The dev cluster must use the Free control plane and one node."
  }

  assert {
    condition     = azurerm_kubernetes_cluster.environment.local_account_disabled && azurerm_kubernetes_cluster.environment.workload_identity_enabled
    error_message = "AKS local accounts must be disabled and workload identity enabled."
  }

  assert {
    condition     = !azurerm_postgresql_flexible_server.environment.public_network_access_enabled && !azurerm_postgresql_flexible_server.environment.authentication[0].password_auth_enabled
    error_message = "PostgreSQL must be private and password authentication must remain disabled."
  }

  assert {
    condition     = !azurerm_search_service.environment.local_authentication_enabled && azurerm_search_service.environment.sku == "basic"
    error_message = "Search must use managed identity-compatible Basic without local keys."
  }

  assert {
    condition     = azurerm_key_vault.environment.network_acls[0].default_action == "Deny"
    error_message = "Key Vault must deny unapproved networks by default."
  }

  assert {
    condition     = azurerm_log_analytics_workspace.environment.daily_quota_gb <= 0.15
    error_message = "Log ingestion must stay within the reviewed daily cap."
  }

  assert {
    condition     = azurerm_consumption_budget_resource_group.environment.amount == 200
    error_message = "The Azure budget must match the reviewed monthly ceiling."
  }
}

run "rejects_excess_telemetry_cap" {
  command = plan

  variables {
    log_daily_quota_gb = 1
  }

  expect_failures = [var.log_daily_quota_gb]
}
