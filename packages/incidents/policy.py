"""Fail-closed automatic rollback policy with explicit approval boundaries."""

from packages.contracts.incident import (
    RollbackPolicy,
    RollbackPolicyCheck,
    RollbackPolicyDecision,
    RollbackPolicyInput,
)


class RollbackPolicyEvaluator:
    @staticmethod
    def evaluate(inputs: RollbackPolicyInput, policy: RollbackPolicy) -> RollbackPolicyDecision:
        if inputs.evaluated_at.tzinfo is None or inputs.evaluated_at.utcoffset() is None:
            raise ValueError("Rollback policy timestamps must be timezone-aware")
        cooldown_elapsed = (
            inputs.last_attempt_at is None
            or (inputs.evaluated_at - inputs.last_attempt_at).total_seconds()
            >= policy.cooldown_seconds
        )
        checks = [
            _check(
                "minimum_evidence",
                inputs.evidence_count >= policy.min_evidence_items,
                "Minimum rollback evidence is present",
                "Rollback evidence is insufficient",
            ),
            _check(
                "cooldown",
                cooldown_elapsed,
                "Rollback cooldown has elapsed",
                "Rollback cooldown is active",
            ),
            _check(
                "attempt_limit",
                inputs.previous_attempts < policy.max_attempts,
                "Rollback attempt limit has capacity",
                "Rollback attempt limit is exhausted",
            ),
            _check(
                "concurrent_rollout",
                not inputs.concurrent_rollout,
                "No concurrent rollout conflicts",
                "Another rollout conflicts with rollback",
            ),
        ]
        approval_reasons = []
        if not inputs.canary_active:
            approval_reasons.append("Stable-production rollback requires human approval")
        if not inputs.guardrail_breached:
            approval_reasons.append("Rollback without a guardrail breach requires human approval")
        if inputs.ambiguous_cause:
            approval_reasons.append("Ambiguous cause requires human approval")
        if inputs.includes_data_migration:
            approval_reasons.append("Data-migration impact requires human approval")
        if inputs.high_risk:
            approval_reasons.append("High-risk rollback requires human approval")
        common_allowed = all(check.passed for check in checks)
        requires_approval = bool(approval_reasons)
        allowed = common_allowed and (not requires_approval or inputs.human_approved)
        reasons = [check.reason for check in checks if not check.passed]
        if requires_approval and not inputs.human_approved:
            reasons.extend(approval_reasons)
        return RollbackPolicyDecision(
            allowed=allowed,
            automatic=allowed and not requires_approval,
            requires_approval=requires_approval,
            checks=checks,
            reasons=reasons,
            evaluated_at=inputs.evaluated_at,
        )


def _check(name: str, passed: bool, success: str, failure: str) -> RollbackPolicyCheck:
    return RollbackPolicyCheck(name=name, passed=passed, reason=success if passed else failure)
