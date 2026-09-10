"""Guarded release promotion state machine."""

from packages.contracts.release import ReleaseGateDecision, ReleaseState

_ALLOWED: dict[ReleaseState, frozenset[ReleaseState]] = {
    ReleaseState.EVALUATED: frozenset(
        {ReleaseState.APPROVED, ReleaseState.REJECTED, ReleaseState.FAILED}
    ),
    ReleaseState.APPROVED: frozenset({ReleaseState.STAGED, ReleaseState.REJECTED}),
    ReleaseState.STAGED: frozenset({ReleaseState.PRODUCTION, ReleaseState.FAILED}),
    ReleaseState.FAILED: frozenset({ReleaseState.APPROVED, ReleaseState.REJECTED}),
    ReleaseState.PRODUCTION: frozenset(),
    ReleaseState.REJECTED: frozenset(),
}


def can_transition(
    current: ReleaseState,
    target: ReleaseState,
    gate: ReleaseGateDecision,
) -> bool:
    if target not in _ALLOWED[current]:
        return False
    if target in {ReleaseState.APPROVED, ReleaseState.STAGED, ReleaseState.PRODUCTION}:
        return gate.passed
    return True


def transition_reason(
    current: ReleaseState,
    target: ReleaseState,
    gate: ReleaseGateDecision,
) -> str:
    if (
        target in {ReleaseState.APPROVED, ReleaseState.STAGED, ReleaseState.PRODUCTION}
        and not gate.passed
    ):
        failed = ", ".join(gate.reasons) or "release gates failed"
        return f"Promotion is blocked: {failed}"
    if target not in _ALLOWED[current]:
        return f"Release cannot transition from {current.value} to {target.value}"
    return "Transition is permitted"


def gate_decision(
    *,
    evaluation_passed: bool,
    dependency_scan_passed: bool,
    image_scan_passed: bool,
    policy_passed: bool,
) -> ReleaseGateDecision:
    reasons: list[str] = []
    if not evaluation_passed:
        reasons.append("evaluation_gate_failed")
    if not dependency_scan_passed:
        reasons.append("dependency_scan_failed")
    if not image_scan_passed:
        reasons.append("image_scan_failed")
    if not policy_passed:
        reasons.append("policy_gate_failed")
    security_passed = dependency_scan_passed and image_scan_passed
    return ReleaseGateDecision(
        passed=evaluation_passed and security_passed and policy_passed,
        evaluation_passed=evaluation_passed,
        security_passed=security_passed,
        policy_passed=policy_passed,
        reasons=reasons,
    )
