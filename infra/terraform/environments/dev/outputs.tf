output "foundation" {
  description = "Non-secret foundation values consumed by later deployment steps."
  value = {
    resource_group      = module.foundation.resource_group
    subnet_ids          = module.foundation.subnet_ids
    container_registry  = module.foundation.container_registry
    deployment_identity = module.foundation.deployment_identity
    workload_identity   = module.foundation.workload_identity
  }
}

output "monthly_cost_limit_usd" {
  description = "Reviewed fixed monthly cost ceiling used by plan policy."
  value       = var.monthly_cost_limit_usd
}
