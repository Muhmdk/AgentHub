"""Fixed-window verification for recovery after a known-good rollback."""

from datetime import datetime

from packages.contracts.incident import (
    RecoveryCheck,
    RecoveryDecision,
    RecoveryObservation,
    RecoveryOutcome,
    RecoveryPolicy,
    RollbackOperation,
    RollbackStatus,
)
from packages.incidents.rollback_repository import RollbackOperationRepository


class RecoveryVerificationError(RuntimeError):
    """Recovery evidence cannot be evaluated against the operation window."""


class RecoveryEvaluator:
    """Evaluate aggregate health only after the fixed observation window closes."""

    @staticmethod
    def evaluate(
        operation: RollbackOperation,
        observation: RecoveryObservation,
        policy: RecoveryPolicy,
        *,
        evaluated_at: datetime,
    ) -> RecoveryDecision:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise RecoveryVerificationError("Recovery evaluation time must be timezone-aware")
        if operation.status is not RollbackStatus.VERIFYING:
            raise RecoveryVerificationError("Rollback is not in recovery verification")
        deadline = operation.verification_deadline
        if deadline is None:
            raise RecoveryVerificationError("Rollback has no fixed verification deadline")

        window_elapsed = evaluated_at >= deadline
        checks = [
            RecoveryCheck(
                name="observation_window",
                passed=(
                    window_elapsed
                    and observation.window_start <= operation.updated_at
                    and observation.window_end >= deadline
                ),
                reason=(
                    "Fixed observation window is complete and fully covered"
                    if window_elapsed
                    and observation.window_start <= operation.updated_at
                    and observation.window_end >= deadline
                    else "Fixed observation window is still open or incompletely covered"
                ),
            ),
            RecoveryCheck(
                name="telemetry_complete",
                passed=observation.telemetry_complete,
                reason=(
                    "Required recovery telemetry is complete"
                    if observation.telemetry_complete
                    else "Required recovery telemetry is missing"
                ),
            ),
            RecoveryCheck(
                name="observation_count",
                passed=observation.observation_count >= policy.min_observations,
                reason=(
                    f"Observed {observation.observation_count} samples; "
                    f"minimum is {policy.min_observations}"
                ),
            ),
            RecoveryCheck(
                name="availability",
                passed=observation.availability >= policy.min_availability,
                reason=(
                    f"Availability {observation.availability:.4f}; "
                    f"minimum is {policy.min_availability:.4f}"
                ),
            ),
            RecoveryCheck(
                name="error_rate",
                passed=observation.error_rate <= policy.max_error_rate,
                reason=(
                    f"Error rate {observation.error_rate:.4f}; "
                    f"maximum is {policy.max_error_rate:.4f}"
                ),
            ),
            RecoveryCheck(
                name="p95_latency",
                passed=observation.p95_latency_ms <= policy.max_p95_latency_ms,
                reason=(
                    f"p95 latency {observation.p95_latency_ms:.2f} ms; "
                    f"maximum is {policy.max_p95_latency_ms:.2f} ms"
                ),
            ),
            RecoveryCheck(
                name="guardrail_health",
                passed=observation.guardrail_healthy,
                reason=(
                    "Operational guardrails are healthy"
                    if observation.guardrail_healthy
                    else "An operational guardrail remains breached"
                ),
            ),
        ]
        if not window_elapsed:
            outcome = RecoveryOutcome.PENDING
            reasons = ["Recovery remains under observation until the fixed deadline"]
        else:
            failed = [check.reason for check in checks if not check.passed]
            outcome = RecoveryOutcome.RECOVERED if not failed else RecoveryOutcome.ESCALATED
            reasons = failed or ["All recovery requirements passed"]
        return RecoveryDecision(
            outcome=outcome,
            checks=checks,
            reasons=reasons,
            source_refs=observation.source_refs,
            evaluated_at=evaluated_at,
        )


class RollbackRecoveryVerifier:
    """Persist recovery lifecycle transitions around deterministic evaluation."""

    def __init__(self, operations: RollbackOperationRepository) -> None:
        self._operations = operations

    def begin(
        self,
        operation: RollbackOperation,
        policy: RecoveryPolicy,
        *,
        started_at: datetime,
    ) -> RollbackOperation:
        return self._operations.begin_verification(operation.id, policy, started_at=started_at)

    def verify(
        self,
        operation: RollbackOperation,
        observation: RecoveryObservation,
        policy: RecoveryPolicy,
        *,
        evaluated_at: datetime,
    ) -> tuple[RecoveryDecision, RollbackOperation]:
        decision = RecoveryEvaluator.evaluate(
            operation, observation, policy, evaluated_at=evaluated_at
        )
        if decision.outcome is RecoveryOutcome.PENDING:
            return decision, operation
        return decision, self._operations.record_recovery(operation.id, decision)
