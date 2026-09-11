"""Deterministic recovery-verification coverage."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from packages.contracts.incident import (
    RecoveryObservation,
    RecoveryOutcome,
    RecoveryPolicy,
    RollbackOperation,
    RollbackPolicyDecision,
    RollbackStatus,
)
from packages.incidents.recovery import RecoveryEvaluator

START = datetime(2026, 9, 11, 7, tzinfo=UTC)


def operation() -> RollbackOperation:
    return RollbackOperation(
        id=uuid4(),
        incident_id=uuid4(),
        route_id=uuid4(),
        target_release_id=uuid4(),
        target_provenance_hash="a" * 64,
        command_hash="b" * 64,
        mode="automatic",
        status=RollbackStatus.VERIFYING,
        attempt_number=1,
        decision=RollbackPolicyDecision(
            allowed=True,
            automatic=True,
            requires_approval=False,
            checks=[],
            reasons=["Eligible active canary guardrail regression"],
            evaluated_at=START,
        ),
        idempotency_key="recovery-operation",
        actor="rollback-controller",
        reason="Restore known-good release",
        route_revision_before=1,
        route_revision_after=2,
        verification_deadline=START + timedelta(minutes=5),
        created_at=START - timedelta(seconds=1),
        updated_at=START,
    )


def observation(**changes: object) -> RecoveryObservation:
    values: dict[str, object] = {
        "window_start": START,
        "window_end": START + timedelta(minutes=5),
        "observation_count": 10,
        "availability": 0.999,
        "error_rate": 0.001,
        "p95_latency_ms": 250,
        "guardrail_healthy": True,
        "telemetry_complete": True,
        "source_refs": ["telemetry://recovery/window"],
    }
    values.update(changes)
    return RecoveryObservation.model_validate(values)


def test_recovery_stays_pending_until_fixed_window_closes() -> None:
    result = RecoveryEvaluator.evaluate(
        operation(), observation(), RecoveryPolicy(), evaluated_at=START + timedelta(minutes=4)
    )

    assert result.outcome is RecoveryOutcome.PENDING


def test_recovery_passes_only_when_every_health_check_passes() -> None:
    result = RecoveryEvaluator.evaluate(
        operation(), observation(), RecoveryPolicy(), evaluated_at=START + timedelta(minutes=5)
    )

    assert result.outcome is RecoveryOutcome.RECOVERED
    assert all(check.passed for check in result.checks)


def test_failed_or_missing_recovery_evidence_escalates() -> None:
    result = RecoveryEvaluator.evaluate(
        operation(),
        observation(
            telemetry_complete=False,
            error_rate=0.08,
            p95_latency_ms=1800,
            guardrail_healthy=False,
        ),
        RecoveryPolicy(),
        evaluated_at=START + timedelta(minutes=5),
    )

    assert result.outcome is RecoveryOutcome.ESCALATED
    assert {check.name for check in result.checks if not check.passed} == {
        "telemetry_complete",
        "error_rate",
        "p95_latency",
        "guardrail_health",
    }
