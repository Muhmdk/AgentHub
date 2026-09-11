"""Policy-constrained rollback coordination with durable retry semantics."""

from datetime import datetime

from packages.contracts.incident import (
    CoordinatedRollbackResult,
    RollbackCommand,
    RollbackPolicy,
    RollbackPolicyDecision,
    RollbackPolicyInput,
)
from packages.incidents.policy import RollbackPolicyEvaluator
from packages.incidents.rollback import KnownGoodRollbackExecutor
from packages.incidents.rollback_repository import RollbackOperationRepository


class RollbackPolicyBlockedError(RuntimeError):
    def __init__(self, decision: RollbackPolicyDecision) -> None:
        super().__init__("; ".join(decision.reasons))
        self.decision = decision


class RollbackCoordinator:
    def __init__(
        self,
        repository: RollbackOperationRepository,
        executor: KnownGoodRollbackExecutor,
        policy: RollbackPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._policy = policy or RollbackPolicy()

    def execute(
        self,
        command: RollbackCommand,
        inputs: RollbackPolicyInput,
        *,
        executed_at: datetime,
    ) -> CoordinatedRollbackResult:
        replay = self._repository.find_by_key(command.request.idempotency_key)
        if replay is not None:
            if replay.command_hash != command.command_hash:
                raise RollbackPolicyBlockedError(
                    RollbackPolicyDecision(
                        allowed=False,
                        automatic=False,
                        requires_approval=False,
                        checks=[],
                        reasons=["Rollback retry token belongs to a different command"],
                        evaluated_at=inputs.evaluated_at,
                    )
                )
            return CoordinatedRollbackResult(replayed=True, operation=replay)
        previous_attempts, last_attempt = self._repository.attempts(command.request.incident_id)
        evaluated = inputs.model_copy(
            update={"previous_attempts": previous_attempts, "last_attempt_at": last_attempt}
        )
        decision = RollbackPolicyEvaluator.evaluate(evaluated, self._policy)
        if not decision.allowed:
            raise RollbackPolicyBlockedError(decision)
        reservation = self._repository.reserve(command, decision)
        if not reservation.created:
            return CoordinatedRollbackResult(replayed=True, operation=reservation.operation)
        try:
            execution = self._executor.execute(command, executed_at=executed_at)
        except Exception:
            self._repository.fail(reservation.operation.id)
            raise
        operation = self._repository.complete(reservation.operation.id, execution.route.revision)
        return CoordinatedRollbackResult(
            replayed=False,
            operation=operation,
            execution=execution,
        )
