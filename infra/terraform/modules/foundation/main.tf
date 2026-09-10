locals {
  compact_name = replace("${var.project}${var.environment}${var.unique_suffix}", "-", "")
  base_name    = "${var.project}-${var.environment}-${var.unique_suffix}"
  mandatory_tags = {
    application = "agenthub"
    environment = var.environment
    managed-by  = "terraform"
    owner       = var.owner
  }
  tags = merge(var.tags, local.mandatory_tags)
}

resource "azurerm_resource_group" "environment" {
  name     = "rg-${local.base_name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "environment" {
  name                = "vnet-${local.base_name}"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.environment.name
  virtual_network_name = azurerm_virtual_network.environment.name
  address_prefixes     = [var.aks_subnet_cidr]

  service_endpoint {
    service = "Microsoft.KeyVault"
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.environment.name
  virtual_network_name = azurerm_virtual_network.environment.name
  address_prefixes     = [var.postgres_subnet_cidr]

  delegation {
    name = "postgres-flexible-server"

    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_network_security_group" "postgres" {
  name                = "nsg-postgres-${local.base_name}"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  tags                = local.tags

  security_rule {
    name                       = "allow-postgres-from-aks"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = var.aks_subnet_cidr
    destination_address_prefix = var.postgres_subnet_cidr
  }

  security_rule {
    name                       = "deny-other-vnet-inbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
  }
}

resource "azurerm_subnet_network_security_group_association" "postgres" {
  subnet_id                 = azurerm_subnet.postgres.id
  network_security_group_id = azurerm_network_security_group.postgres.id
}

resource "azurerm_container_registry" "environment" {
  name                          = substr("acr${local.compact_name}", 0, 50)
  resource_group_name           = azurerm_resource_group.environment.name
  location                      = azurerm_resource_group.environment.location
  sku                           = "Basic"
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  public_network_access_enabled = true
  tags                          = local.tags
}

resource "azurerm_user_assigned_identity" "deployment" {
  name                = "id-deploy-${local.base_name}"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github_environment" {
  name                      = "github-${var.github_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.deployment.id
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_repository}:environment:${var.github_environment}"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_role_assignment" "deployment_contributor" {
  scope                = azurerm_resource_group.environment.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.deployment.principal_id
}

resource "azurerm_role_assignment" "deployment_rbac_administrator" {
  scope                = azurerm_resource_group.environment.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.deployment.principal_id
}

resource "azurerm_user_assigned_identity" "workload" {
  name                = "id-workload-${local.base_name}"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  tags                = local.tags
}
