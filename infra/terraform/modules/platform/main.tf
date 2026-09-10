locals {
  base_name = "${var.project}-${var.environment}-${var.unique_suffix}"
  mandatory_tags = {
    application = "agenthub"
    environment = var.environment
    managed-by  = "terraform"
    owner       = var.owner
  }
  tags = merge(var.tags, local.mandatory_tags)
}

resource "azurerm_log_analytics_workspace" "environment" {
  name                           = "log-${local.base_name}"
  resource_group_name            = var.resource_group.name
  location                       = var.resource_group.location
  sku                            = "PerGB2018"
  retention_in_days              = 30
  daily_quota_gb                 = var.log_daily_quota_gb
  local_authentication_enabled   = false
  internet_ingestion_access_type = "Enabled"
  internet_query_access_type     = "Enabled"
  tags                           = local.tags
}

resource "azurerm_application_insights" "environment" {
  name                                 = "appi-${local.base_name}"
  resource_group_name                  = var.resource_group.name
  location                             = var.resource_group.location
  workspace_id                         = azurerm_log_analytics_workspace.environment.id
  application_type                     = "web"
  retention_in_days                    = 30
  daily_data_cap_in_gb                 = var.log_daily_quota_gb
  daily_data_cap_notifications_enabled = true
  local_authentication_enabled         = false
  internet_ingestion_enabled           = true
  internet_query_enabled               = true
  ip_masking_enabled                   = true
  sampling_percentage                  = 100
  tags                                 = local.tags
}

resource "azurerm_public_ip" "aks_egress" {
  name                = "pip-aks-egress-${local.base_name}"
  resource_group_name = var.resource_group.name
  location            = var.resource_group.location
  allocation_method   = "Static"
  sku                 = "Standard"
  sku_tier            = "Regional"
  tags                = local.tags
}

resource "azurerm_kubernetes_cluster" "environment" {
  name                = "aks-${local.base_name}"
  resource_group_name = var.resource_group.name
  location            = var.resource_group.location
  dns_prefix          = "aks-${local.base_name}"
  sku_tier            = "Free"

  role_based_access_control_enabled = true
  local_account_disabled            = true
  oidc_issuer_enabled               = true
  workload_identity_enabled         = true
  azure_policy_enabled              = true
  image_cleaner_enabled             = true
  image_cleaner_interval_hours      = 168
  run_command_enabled               = false
  cost_analysis_enabled             = false
  automatic_upgrade_channel         = "patch"
  node_os_upgrade_channel           = "NodeImage"

  default_node_pool {
    name                         = "system"
    vm_size                      = var.node_vm_size
    node_count                   = 1
    auto_scaling_enabled         = false
    only_critical_addons_enabled = false
    node_public_ip_enabled       = false
    os_disk_size_gb              = 32
    os_disk_type                 = "Managed"
    os_sku                       = "AzureLinux3"
    vnet_subnet_id               = var.aks_subnet_id
    max_pods                     = 60
    temporary_name_for_rotation  = "systemtmp"
    tags                         = local.tags

    upgrade_settings {
      max_surge                     = "10%"
      drain_timeout_in_minutes      = 30
      node_soak_duration_in_minutes = 0
    }
  }

  node_provisioning_profile {
    mode = "Manual"
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [var.aks_identities.control_plane.id]
  }

  kubelet_identity {
    client_id                 = var.aks_identities.kubelet.client_id
    object_id                 = var.aks_identities.kubelet.principal_id
    user_assigned_identity_id = var.aks_identities.kubelet.id
  }

  azure_active_directory_role_based_access_control {
    tenant_id              = var.tenant_id
    azure_rbac_enabled     = true
    admin_group_object_ids = var.aks_admin_group_object_ids
  }

  api_server_access_profile {
    authorized_ip_ranges = var.aks_api_authorized_ip_ranges
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
    pod_cidr            = "10.244.0.0/16"
    service_cidr        = "10.0.0.0/16"
    dns_service_ip      = "10.0.0.10"

    load_balancer_profile {
      outbound_ip_address_ids = [azurerm_public_ip.aks_egress.id]
      idle_timeout_in_minutes = 4
    }
  }

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m" # pragma: allowlist secret
  }

  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.environment.id
    msi_auth_for_monitoring_enabled = true
  }

  tags = local.tags
}

resource "azurerm_role_assignment" "registry_pull" {
  scope                = var.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = var.aks_identities.kubelet.principal_id
}

resource "azurerm_user_assigned_identity" "database_bootstrap" {
  name                = "id-database-bootstrap-${local.base_name}"
  resource_group_name = var.resource_group.name
  location            = var.resource_group.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "workload" {
  name                      = "aks-agenthub"
  user_assigned_identity_id = var.workload_identity.id
  issuer                    = azurerm_kubernetes_cluster.environment.oidc_issuer_url
  subject                   = "system:serviceaccount:agenthub:agenthub"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_federated_identity_credential" "database_bootstrap" {
  name                      = "aks-database-bootstrap"
  user_assigned_identity_id = azurerm_user_assigned_identity.database_bootstrap.id
  issuer                    = azurerm_kubernetes_cluster.environment.oidc_issuer_url
  subject                   = "system:serviceaccount:agenthub:agenthub-database-bootstrap"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = var.resource_group.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                 = "link-${local.base_name}"
  private_dns_zone_id  = azurerm_private_dns_zone.postgres.id
  virtual_network_id   = var.virtual_network_id
  registration_enabled = false
  tags                 = local.tags
}

resource "azurerm_postgresql_flexible_server" "environment" {
  name                          = "psql-${local.base_name}"
  resource_group_name           = var.resource_group.name
  location                      = var.resource_group.location
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  auto_grow_enabled             = true
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  delegated_subnet_id           = var.postgres_subnet_id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "database_bootstrap" {
  server_name         = azurerm_postgresql_flexible_server.environment.name
  resource_group_name = var.resource_group.name
  tenant_id           = var.tenant_id
  object_id           = azurerm_user_assigned_identity.database_bootstrap.principal_id
  principal_name      = azurerm_user_assigned_identity.database_bootstrap.name
  principal_type      = "ServicePrincipal"
}

resource "azurerm_key_vault" "environment" {
  name                          = substr("kv-${local.base_name}", 0, 24)
  resource_group_name           = var.resource_group.name
  location                      = var.resource_group.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  public_network_access_enabled = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = true
  tags                          = local.tags

  network_acls {
    bypass                     = "AzureServices"
    default_action             = "Deny"
    ip_rules                   = var.key_vault_operator_ip_rules
    virtual_network_subnet_ids = [var.aks_subnet_id]
  }
}

resource "azurerm_search_service" "environment" {
  name                          = "srch-${local.base_name}"
  resource_group_name           = var.resource_group.name
  location                      = var.resource_group.location
  sku                           = "basic"
  replica_count                 = 1
  partition_count               = 1
  semantic_search_sku           = "free"
  local_authentication_enabled  = false
  public_network_access_enabled = true
  allowed_ips                   = [azurerm_public_ip.aks_egress.ip_address]
  network_rule_bypass_option    = "None"
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "workload_key_vault" {
  scope                = azurerm_key_vault.environment.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.workload_identity.principal_id
}

resource "azurerm_role_assignment" "workload_search" {
  scope                = azurerm_search_service.environment.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = var.workload_identity.principal_id
}

resource "azurerm_role_assignment" "workload_monitor" {
  scope                = azurerm_application_insights.environment.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = var.workload_identity.principal_id
}

resource "azurerm_consumption_budget_resource_group" "environment" {
  name              = "budget-${local.base_name}"
  resource_group_id = var.resource_group.id
  amount            = var.monthly_cost_limit_usd
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  dynamic "notification" {
    for_each = toset([50, 75, 90, 100])

    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.budget_contact_emails
      contact_roles  = ["Owner"]
    }
  }
}
