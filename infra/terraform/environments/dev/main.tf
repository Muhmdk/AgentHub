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
