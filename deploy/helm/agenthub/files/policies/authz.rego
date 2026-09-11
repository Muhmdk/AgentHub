package agenthub.authz

import rego.v1

decision := {
	"schema_version": "agenthub.dev/policy-decision/v1",
	"allow": false,
	"reasons": ["unsupported_action"],
	"policy_bundle_version": data.agenthub.config.policy_bundle_version,
	"obligations": default_obligations,
} if {
	not supported_action
}

decision := {
	"schema_version": "agenthub.dev/policy-decision/v1",
	"allow": count(deployment_denials) == 0,
	"reasons": decision_reasons,
	"policy_bundle_version": data.agenthub.config.policy_bundle_version,
	"obligations": default_obligations,
} if {
	deployment_action
}

deployment_action if input.action.kind in {"registration", "promotion"}

runtime_action if input.action.kind in {"model_invocation", "tool_execution"}

supported_action if deployment_action

supported_action if runtime_action

decision := {
	"schema_version": "agenthub.dev/policy-decision/v1",
	"allow": count(runtime_denials) == 0,
	"reasons": runtime_decision_reasons,
	"policy_bundle_version": data.agenthub.config.policy_bundle_version,
	"obligations": runtime_obligations,
} if {
	runtime_action
}

default_obligations := {
	"audit": true,
	"redact_pii": false,
	"max_input_tokens": null,
	"max_output_tokens": null,
	"timeout_ms": null,
	"rate_limit_per_minute": null,
}

runtime_obligations := object.union(default_obligations, {
	"redact_pii": redact_pii,
	"max_input_tokens": data.agenthub.config.runtime_limits.max_input_tokens,
	"max_output_tokens": data.agenthub.config.runtime_limits.max_output_tokens,
	"timeout_ms": data.agenthub.config.runtime_limits.timeout_ms,
	"rate_limit_per_minute": data.agenthub.config.runtime_limits.rate_limit_per_minute,
})

redact_pii if {
	input.action.kind == "model_invocation"
	input.action.external_provider
	"pii" in input.action.data_classes
} else := false

decision_reasons := sort([reason | some reason in deployment_denials]) if {
	count(deployment_denials) > 0
}

decision_reasons := [sprintf("%s_allowed", [input.action.kind])] if {
	count(deployment_denials) == 0
}

runtime_decision_reasons := sort([reason | some reason in runtime_denials]) if {
	count(runtime_denials) > 0
}

runtime_decision_reasons := [sprintf("%s_allowed", [input.action.kind])] if {
	count(runtime_denials) == 0
}

runtime_denials contains "local_identity_forbidden" if {
	input.context.environment in {"staging", "production"}
	input.subject.authentication_method == "local-explicit"
}

runtime_denials contains "tool_not_declared" if {
	input.action.kind == "tool_execution"
	count(named_tool_grants) == 0
}

runtime_denials contains "tool_access_not_allowed" if {
	input.action.kind == "tool_execution"
	count(named_tool_grants) > 0
	count(access_tool_grants) == 0
}

runtime_denials contains "missing_scope" if {
	input.action.kind == "tool_execution"
	some scope in input.action.required_scopes
	not tool_scope_allowed(scope)
}

runtime_denials contains "model_not_declared" if {
	input.action.kind == "model_invocation"
	input.action.provider != input.agent.model.provider
}

runtime_denials contains "model_not_declared" if {
	input.action.kind == "model_invocation"
	input.action.model != input.agent.model.model
}

runtime_denials contains "model_provider_not_allowed" if {
	input.action.kind == "model_invocation"
	allowed_providers := data.agenthub.config.allowed_model_providers[input.context.environment]
	not input.action.provider in allowed_providers
}

runtime_denials contains "input_token_budget_exceeded" if {
	input.action.kind == "model_invocation"
	input.action.requested_input_tokens > data.agenthub.config.runtime_limits.max_input_tokens
}

runtime_denials contains "output_token_budget_exceeded" if {
	input.action.kind == "model_invocation"
	input.action.requested_output_tokens > data.agenthub.config.runtime_limits.max_output_tokens
}

named_tool_grants := [grant | some grant in input.agent.tools; grant.name == input.action.tool_name]

access_tool_grants := [grant |
	some grant in named_tool_grants
	grant.access == input.action.access
]

tool_scope_allowed(scope) if {
	some grant in access_tool_grants
	scope in grant.scopes
}

deployment_denials contains "local_identity_forbidden" if {
	input.context.environment in {"staging", "production"}
	input.subject.authentication_method == "local-explicit"
}

deployment_denials contains "local_identity_forbidden" if {
	input.context.environment in {"staging", "production"}
	startswith(input.subject.identity, "local/")
}

deployment_denials contains "model_provider_not_allowed" if {
	input.action.kind == "registration"
	allowed_providers := data.agenthub.config.allowed_model_providers[input.context.environment]
	not input.agent.model.provider in allowed_providers
}

deployment_denials contains "write_tool_risk_tier_forbidden" if {
	input.action.kind == "registration"
	input.agent.risk_tier in {"low", "medium"}
	some tool in input.agent.tools
	tool.access == "write"
}

deployment_denials contains "evaluation_gate_failed" if {
	input.action.kind == "promotion"
	not input.action.evaluation_passed
}

deployment_denials contains "security_gate_failed" if {
	input.action.kind == "promotion"
	not input.action.security_passed
}

deployment_denials contains "target_environment_mismatch" if {
	input.action.kind == "promotion"
	input.action.target_environment != input.context.environment
}

deployment_denials contains "model_provider_not_allowed" if {
	input.action.kind == "promotion"
	allowed_providers := data.agenthub.config.allowed_model_providers[input.action.target_environment]
	not input.agent.model.provider in allowed_providers
}

deployment_denials contains "critical_risk_production_forbidden" if {
	input.action.kind == "promotion"
	input.action.target_environment == "production"
	input.agent.risk_tier == "critical"
}

deployment_denials contains "insufficient_human_approvals" if {
	input.action.kind == "promotion"
	required := required_approval_count
	count(approval_identities) < required
}

deployment_denials contains "self_approval_forbidden" if {
	input.action.kind == "promotion"
	input.action.target_environment == "production"
	some approval in input.action.approvals
	approval.approver == input.subject.identity
}

deployment_denials contains "approval_after_request" if {
	input.action.kind == "promotion"
	some approval in input.action.approvals
	time.parse_rfc3339_ns(approval.approved_at) > time.parse_rfc3339_ns(input.context.occurred_at)
}

approval_identities := {approval.approver | some approval in input.action.approvals}

required_approval_count := 2 if {
	input.action.target_environment == "production"
	input.agent.risk_tier in {"high", "critical"}
} else := 1 if {
	input.action.target_environment == "production"
	input.agent.risk_tier in {"low", "medium"}
} else := 0
