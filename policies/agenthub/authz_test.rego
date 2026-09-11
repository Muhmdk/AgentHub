package agenthub.authz_test

import data.agenthub.authz.decision
import rego.v1

test_local_registration_is_allowed if {
	result := decision with input as registration_input("local", "medium", "fake", read_tools)
	result.allow
	result.reasons == ["registration_allowed"]
	result.obligations.audit
}

test_deployed_local_identity_is_denied if {
	candidate := registration_input("staging", "medium", "fake", read_tools)
	local_candidate := object.union(candidate, {"subject": object.union(candidate.subject, {
		"identity": "local/operator",
		"authentication_method": "local-explicit",
	})})
	result := decision with input as local_candidate
	not result.allow
	"local_identity_forbidden" in result.reasons
}

test_low_and_medium_risk_write_tools_are_denied if {
	result := decision with input as registration_input("local", "medium", "fake", write_tools)
	not result.allow
	"write_tool_risk_tier_forbidden" in result.reasons
}

test_production_registration_rejects_unapproved_model_provider if {
	result := decision with input as registration_input("production", "medium", "fake", read_tools)
	not result.allow
	"model_provider_not_allowed" in result.reasons
}

test_promotion_requires_passing_evaluation_and_security if {
	candidate := promotion_input("staging", "medium", "fake", [])
	failed := object.union(candidate, {"action": object.union(candidate.action, {
		"evaluation_passed": false,
		"security_passed": false,
	})})
	result := decision with input as failed
	not result.allow
	"evaluation_gate_failed" in result.reasons
	"security_gate_failed" in result.reasons
}

test_promotion_environment_must_match_evaluation_context if {
	candidate := promotion_input("staging", "medium", "fake", [])
	mismatched := object.union(candidate, {"action": object.union(candidate.action, {"target_environment": "production"})})
	result := decision with input as mismatched
	not result.allow
	"target_environment_mismatch" in result.reasons
}

test_medium_risk_production_requires_one_independent_approval if {
	denied := decision with input as promotion_input("production", "medium", "azure-openai", [])
	allowed := decision with input as promotion_input("production", "medium", "azure-openai", [approval("human/reviewer-one", "2026-09-10T14:00:00Z")])
	not denied.allow
	"insufficient_human_approvals" in denied.reasons
	allowed.allow
}

test_high_risk_production_requires_two_distinct_approvals if {
	one_approval := decision with input as promotion_input("production", "high", "azure-openai", [approval("human/reviewer-one", "2026-09-10T14:00:00Z")])
	duplicate_approval := decision with input as promotion_input("production", "high", "azure-openai", [
		approval("human/reviewer-one", "2026-09-10T13:00:00Z"),
		approval("human/reviewer-one", "2026-09-10T14:00:00Z"),
	])
	allowed := decision with input as promotion_input("production", "high", "azure-openai", [
		approval("human/reviewer-one", "2026-09-10T13:00:00Z"),
		approval("human/reviewer-two", "2026-09-10T14:00:00Z"),
	])
	not one_approval.allow
	not duplicate_approval.allow
	allowed.allow
}

test_requester_cannot_approve_own_production_promotion if {
	result := decision with input as promotion_input("production", "medium", "azure-openai", [approval("service/release", "2026-09-10T14:00:00Z")])
	not result.allow
	"self_approval_forbidden" in result.reasons
}

test_future_approval_is_denied if {
	result := decision with input as promotion_input("production", "medium", "azure-openai", [approval("human/reviewer-one", "2026-09-10T16:00:00Z")])
	not result.allow
	"approval_after_request" in result.reasons
}

test_critical_risk_production_is_denied if {
	result := decision with input as promotion_input("production", "critical", "azure-openai", [
		approval("human/reviewer-one", "2026-09-10T13:00:00Z"),
		approval("human/reviewer-two", "2026-09-10T14:00:00Z"),
	])
	not result.allow
	"critical_risk_production_forbidden" in result.reasons
}

test_declared_read_tool_and_scope_are_allowed if {
	result := decision with input as tool_input("inventory.read", ["inventory:read"], "read")
	result.allow
	result.reasons == ["tool_execution_allowed"]
}

test_undeclared_cross_agent_and_write_tools_are_denied if {
	cross_agent := decision with input as tool_input("customer-profile.read", ["customer:read"], "read")
	write := decision with input as tool_input("inventory.read", ["inventory:write"], "write")
	not cross_agent.allow
	"tool_not_declared" in cross_agent.reasons
	not write.allow
	"tool_access_not_allowed" in write.reasons
}

test_missing_tool_scope_is_denied if {
	result := decision with input as tool_input("inventory.read", ["inventory:admin"], "read")
	not result.allow
	"missing_scope" in result.reasons
}

test_declared_model_is_allowed_with_bounded_obligations if {
	result := decision with input as model_input("local", "fake", "deterministic-v1", 800)
	result.allow
	result.obligations.max_output_tokens == 4096
	result.obligations.timeout_ms == 10000
}

test_undeclared_or_environment_forbidden_model_is_denied if {
	undeclared := decision with input as model_input("local", "fake", "other-model", 800)
	forbidden := decision with input as model_input("production", "fake", "deterministic-v1", 800)
	not undeclared.allow
	"model_not_declared" in undeclared.reasons
	not forbidden.allow
	"model_provider_not_allowed" in forbidden.reasons
}

test_requested_model_token_budget_is_denied if {
	result := decision with input as model_input("local", "fake", "deterministic-v1", 5000)
	not result.allow
	"output_token_budget_exceeded" in result.reasons
}

test_model_token_budget_exact_boundary_is_allowed_and_overage_is_denied if {
	base := model_input("local", "fake", "deterministic-v1", 4096)
	exact := object.union(base, {"action": object.union(base.action, {"requested_input_tokens": 16000})})
	over := object.union(base, {"action": object.union(base.action, {
		"requested_input_tokens": 16001,
		"requested_output_tokens": 4097,
	})})
	exact_result := decision with input as exact
	over_result := decision with input as over
	exact_result.allow
	not over_result.allow
	"input_token_budget_exceeded" in over_result.reasons
	"output_token_budget_exceeded" in over_result.reasons
}

test_external_pii_sets_redaction_obligation if {
	candidate := model_input("staging", "azure-openai", "gpt-deployment", 800)
	pii_action := object.union(candidate.action, {
		"data_classes": ["internal", "pii"],
		"external_provider": true,
	})
	pii_agent := object.union(candidate.agent, {"model": {
		"provider": "azure-openai",
		"model": "gpt-deployment",
	}})
	pii_candidate := object.union(candidate, {"action": pii_action, "agent": pii_agent})
	result := decision with input as pii_candidate
	result.allow
	result.obligations.redact_pii
}

test_local_pii_does_not_require_external_redaction if {
	candidate := model_input("local", "fake", "deterministic-v1", 800)
	pii_action := object.union(candidate.action, {"data_classes": ["internal", "pii"]})
	result := decision with input as object.union(candidate, {"action": pii_action})
	result.allow
	not result.obligations.redact_pii
}

read_tools := [{
	"name": "inventory.read",
	"scopes": ["inventory:read"],
	"access": "read",
}]

write_tools := [{
	"name": "inventory.write",
	"scopes": ["inventory:write"],
	"access": "write",
}]

registration_input(environment, risk_tier, provider, tools) := {
	"schema_version": "agenthub.dev/policy-input/v1",
	"subject": service_subject,
	"agent": agent(risk_tier, provider, tools),
	"action": {
		"kind": "registration",
		"manifest_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"source_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	},
	"context": request_context(environment),
}

promotion_input(environment, risk_tier, provider, approvals) := {
	"schema_version": "agenthub.dev/policy-input/v1",
	"subject": service_subject,
	"agent": agent(risk_tier, provider, read_tools),
	"action": {
		"kind": "promotion",
		"target_environment": environment,
		"evaluation_passed": true,
		"security_passed": true,
		"approvals": approvals,
	},
	"context": request_context(environment),
}

tool_input(tool_name, required_scopes, access) := {
	"schema_version": "agenthub.dev/policy-input/v1",
	"subject": service_subject,
	"agent": agent("medium", "fake", read_tools),
	"action": {
		"kind": "tool_execution",
		"tool_name": tool_name,
		"required_scopes": required_scopes,
		"access": access,
		"arguments_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
	},
	"context": request_context("local"),
}

model_input(environment, provider, model_name, output_tokens) := {
	"schema_version": "agenthub.dev/policy-input/v1",
	"subject": service_subject,
	"agent": agent("medium", provider, read_tools),
	"action": {
		"kind": "model_invocation",
		"provider": provider,
		"model": model_name,
		"requested_input_tokens": 100,
		"requested_output_tokens": output_tokens,
		"data_classes": ["internal"],
		"external_provider": false,
	},
	"context": request_context(environment),
}

service_subject := {
	"identity": "service/release",
	"kind": "service",
	"authentication_method": "workload-identity",
	"roles": ["release-orchestrator"],
}

agent(risk_tier, provider, tools) := {
	"name": "inventory-agent",
	"version": "1.0.0",
	"owner": "retail-ai-team",
	"risk_tier": risk_tier,
	"tools": tools,
	"model": {
		"provider": provider,
		"model": "deterministic-v1",
	},
}

request_context(environment) := {
	"environment": environment,
	"correlation_id": "rego-test-1",
	"occurred_at": "2026-09-10T15:00:00Z",
	"release_id": "release-42",
}

approval(approver, approved_at) := {
	"approver": approver,
	"approved_at": approved_at,
}
