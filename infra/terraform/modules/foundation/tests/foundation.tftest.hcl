mock_provider "azurerm" {}

variables {
  project              = "agenthub"
  environment          = "dev"
  location             = "canadacentral"
  unique_suffix        = "a1b2"
  owner                = "Muhammad Khan"
  github_repository    = "Muhmdk/AgentHub"
  github_environment   = "staging"
  vnet_cidr            = "10.40.0.0/16"
  aks_subnet_cidr      = "10.40.0.0/20"
  postgres_subnet_cidr = "10.40.16.0/24"
}

run "plans_cost_conscious_secure_foundation" {
  command = plan

  assert {
    condition     = azurerm_resource_group.environment.name == "rg-agenthub-dev-a1b2"
    error_message = "The resource group must include the explicit project, environment, and suffix."
  }

  assert {
    condition     = azurerm_container_registry.environment.sku == "Basic"
    error_message = "The dev registry must retain the reviewed Basic SKU."
  }

  assert {
    condition     = !azurerm_container_registry.environment.admin_enabled && !azurerm_container_registry.environment.anonymous_pull_enabled
    error_message = "Registry administrator and anonymous pull access must remain disabled."
  }

  assert {
    condition     = azurerm_federated_identity_credential.github_environment.subject == "repo:Muhmdk/AgentHub:environment:staging"
    error_message = "GitHub federation must be scoped to the protected environment."
  }

  assert {
    condition = one([
      for rule in azurerm_network_security_group.postgres.security_rule : rule.source_address_prefix
      if rule.name == "allow-postgres-from-aks"
    ]) == "10.40.0.0/20"
    error_message = "PostgreSQL access must originate from the AKS subnet only."
  }

  assert {
    condition     = azurerm_resource_group.environment.tags["managed-by"] == "terraform"
    error_message = "Mandatory governance tags must not be overridden."
  }
}

run "rejects_unreviewed_environment" {
  command = plan

  variables {
    environment = "production"
  }

  expect_failures = [var.environment]
}
