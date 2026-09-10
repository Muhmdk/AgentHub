output "foundation" {
  description = "Non-secret foundation values consumed by later deployment steps."
  value = {
    resource_group      = module.foundation.resource_group
    virtual_network_id  = module.foundation.virtual_network_id
    subnet_ids          = module.foundation.subnet_ids
    container_registry  = module.foundation.container_registry
    aks_identities      = module.foundation.aks_identities
    deployment_identity = module.foundation.deployment_identity
    workload_identity   = module.foundation.workload_identity
  }
}

output "platform" {
  description = "Non-secret endpoints and identities used by deployment and verification."
  value       = module.platform
}

output "monthly_cost_limit_usd" {
  description = "Reviewed fixed monthly cost ceiling used by plan policy."
  value       = var.monthly_cost_limit_usd
}
