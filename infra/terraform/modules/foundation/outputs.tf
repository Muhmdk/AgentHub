output "resource_group" {
  description = "Environment resource group."
  value = {
    id       = azurerm_resource_group.environment.id
    name     = azurerm_resource_group.environment.name
    location = azurerm_resource_group.environment.location
  }
}

output "subnet_ids" {
  description = "Subnets consumed by the independently managed platform resources."
  value = {
    aks      = azurerm_subnet.aks.id
    postgres = azurerm_subnet.postgres.id
  }
}

output "virtual_network_id" {
  description = "Virtual network used for private DNS links and platform resources."
  value       = azurerm_virtual_network.environment.id
}

output "container_registry" {
  description = "Registry identity and login endpoint."
  value = {
    id           = azurerm_container_registry.environment.id
    name         = azurerm_container_registry.environment.name
    login_server = azurerm_container_registry.environment.login_server
  }
}

output "deployment_identity" {
  description = "Identity trusted by the protected GitHub environment."
  value = {
    id           = azurerm_user_assigned_identity.deployment.id
    name         = azurerm_user_assigned_identity.deployment.name
    client_id    = azurerm_user_assigned_identity.deployment.client_id
    principal_id = azurerm_user_assigned_identity.deployment.principal_id
  }
}

output "workload_identity" {
  description = "Identity federated to the AgentHub Kubernetes service account by the platform module."
  value = {
    id           = azurerm_user_assigned_identity.workload.id
    name         = azurerm_user_assigned_identity.workload.name
    client_id    = azurerm_user_assigned_identity.workload.client_id
    principal_id = azurerm_user_assigned_identity.workload.principal_id
  }
}

output "aks_identities" {
  description = "Pre-authorized control-plane and kubelet identities for deterministic AKS creation."
  value = {
    control_plane = {
      id           = azurerm_user_assigned_identity.aks_control_plane.id
      client_id    = azurerm_user_assigned_identity.aks_control_plane.client_id
      principal_id = azurerm_user_assigned_identity.aks_control_plane.principal_id
    }
    kubelet = {
      id           = azurerm_user_assigned_identity.aks_kubelet.id
      client_id    = azurerm_user_assigned_identity.aks_kubelet.client_id
      principal_id = azurerm_user_assigned_identity.aks_kubelet.principal_id
    }
  }

  depends_on = [
    azurerm_role_assignment.aks_control_plane_network,
    azurerm_role_assignment.aks_control_plane_kubelet_identity,
  ]
}
