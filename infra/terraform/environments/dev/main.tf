module "foundation" {
  source = "../../modules/foundation"

  project              = var.project
  environment          = var.environment
  location             = var.location
  unique_suffix        = var.unique_suffix
  owner                = var.owner
  github_repository    = var.github_repository
  github_environment   = var.github_environment
  vnet_cidr            = var.vnet_cidr
  aks_subnet_cidr      = var.aks_subnet_cidr
  postgres_subnet_cidr = var.postgres_subnet_cidr
  tags                 = var.tags
}

module "platform" {
  source = "../../modules/platform"

  tenant_id                    = var.tenant_id
  project                      = var.project
  environment                  = var.environment
  unique_suffix                = var.unique_suffix
  owner                        = var.owner
  resource_group               = module.foundation.resource_group
  virtual_network_id           = module.foundation.virtual_network_id
  aks_subnet_id                = module.foundation.subnet_ids.aks
  postgres_subnet_id           = module.foundation.subnet_ids.postgres
  container_registry_id        = module.foundation.container_registry.id
  aks_identities               = module.foundation.aks_identities
  workload_identity            = module.foundation.workload_identity
  azure_openai_resource_id     = var.azure_openai_resource_id
  aks_admin_group_object_ids   = var.aks_admin_group_object_ids
  aks_api_authorized_ip_ranges = var.aks_api_authorized_ip_ranges
  key_vault_operator_ip_rules  = var.key_vault_operator_ip_rules
  monthly_cost_limit_usd       = var.monthly_cost_limit_usd
  budget_contact_emails        = var.budget_contact_emails
  budget_start_date            = var.budget_start_date
  tags                         = var.tags
}
