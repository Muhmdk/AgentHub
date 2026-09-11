"""Deterministic operational fault scenarios for incident recovery drills."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from packages.contracts.delivery import DeliveryEnvironment
from packages.contracts.incident import (
    EvidenceInput,
    EvidenceKind,
    IncidentSeverity,
    IncidentSignal,
    IncidentTriggerType,
    RecoveryObservation,
)
from packages.contracts.manifest import Slug


@dataclass(frozen=True)
class TopKMeasurement:
    """Reproducible p95 latency components for one retrieval configuration."""

    top_k: int
    retrieval_p95_latency_ms: float
    model_p95_latency_ms: float
    agent_p95_latency_ms: float


@dataclass(frozen=True)
class TopKRegressionScenario:
    """Fault measurements plus the exact trigger and evidence they generate."""

    baseline: TopKMeasurement
    candidate: TopKMeasurement
    signal: IncidentSignal
    evidence: tuple[EvidenceInput, ...]


class TopKRegressionFault:
    """Inject retrieval fan-out while holding model latency constant."""

    def __init__(
        self,
        *,
        baseline_top_k: int = 5,
        candidate_top_k: int = 50,
        retrieval_base_ms: float = 50,
        per_result_ms: float = 9,
        model_p95_latency_ms: float = 200,
        regression_threshold_ratio: float = 1.5,
    ) -> None:
        if not 1 <= baseline_top_k < candidate_top_k <= 100:
            raise ValueError("Fault requires 1 <= baseline top-k < candidate top-k <= 100")
        if min(retrieval_base_ms, per_result_ms, model_p95_latency_ms) < 0:
            raise ValueError("Fault latency components cannot be negative")
        if regression_threshold_ratio <= 1:
            raise ValueError("Regression threshold ratio must be greater than one")
        self._baseline_top_k = baseline_top_k
        self._candidate_top_k = candidate_top_k
        self._retrieval_base_ms = retrieval_base_ms
        self._per_result_ms = per_result_ms
        self._model_ms = model_p95_latency_ms
        self._threshold_ratio = regression_threshold_ratio

    def build(
        self,
        *,
        agent_name: Slug,
        environment: DeliveryEnvironment,
        release_id: UUID,
        route_id: UUID,
        canary_rollout_id: UUID,
        observed_at: datetime,
    ) -> TopKRegressionScenario:
        baseline = self._measure(self._baseline_top_k)
        candidate = self._measure(self._candidate_top_k)
        threshold = baseline.agent_p95_latency_ms * self._threshold_ratio
        signal = IncidentSignal(
            idempotency_key=f"top-k-{canary_rollout_id}-trigger",
            trigger_type=IncidentTriggerType.CANARY_GUARDRAIL_FAILURE,
            severity=IncidentSeverity.CRITICAL,
            agent_name=agent_name,
            environment=environment,
            signal_name="agent.p95_latency_ms",
            observed_value=candidate.agent_p95_latency_ms,
            threshold=threshold,
            observed_at=observed_at,
            source_ref=f"fault://top-k/{canary_rollout_id}/agent-p95",
            summary=(
                f"Retrieval top-k {self._baseline_top_k} to {self._candidate_top_k} "
                "breached the canary p95 latency guardrail"
            ),
            release_id=release_id,
            route_id=route_id,
            canary_rollout_id=canary_rollout_id,
        )
        retrieval_ratio = candidate.retrieval_p95_latency_ms / baseline.retrieval_p95_latency_ms - 1
        evidence = (
            EvidenceInput(
                idempotency_key=f"top-k-{canary_rollout_id}-config",
                kind=EvidenceKind.CONFIG_DIFF,
                source_ref=f"fault://top-k/{canary_rollout_id}/config",
                summary=(
                    f"Retrieval top-k changed from {self._baseline_top_k} "
                    f"to {self._candidate_top_k}"
                ),
                occurred_at=observed_at - timedelta(minutes=5),
                subject_id=f"{agent_name}-config",
                attributes={
                    "changes": {
                        "spec.retrieval.top_k": {
                            "before": self._baseline_top_k,
                            "after": self._candidate_top_k,
                        }
                    }
                },
            ),
            EvidenceInput(
                idempotency_key=f"top-k-{canary_rollout_id}-retrieval",
                kind=EvidenceKind.METRIC,
                source_ref=f"fault://top-k/{canary_rollout_id}/retrieval-p95",
                summary="Candidate retrieval p95 latency increased under fan-out",
                occurred_at=observed_at,
                subject_id="retrieval.duration_ms",
                attributes={
                    "baseline": baseline.retrieval_p95_latency_ms,
                    "current": candidate.retrieval_p95_latency_ms,
                    "delta": (
                        candidate.retrieval_p95_latency_ms - baseline.retrieval_p95_latency_ms
                    ),
                    "change_ratio": retrieval_ratio,
                },
            ),
            EvidenceInput(
                idempotency_key=f"top-k-{canary_rollout_id}-model",
                kind=EvidenceKind.METRIC,
                source_ref=f"fault://top-k/{canary_rollout_id}/model-p95",
                summary="Model p95 latency remained unchanged during the fault",
                occurred_at=observed_at,
                subject_id="model.duration_ms",
                attributes={
                    "baseline": baseline.model_p95_latency_ms,
                    "current": candidate.model_p95_latency_ms,
                    "delta": 0,
                    "change_ratio": 0,
                },
            ),
        )
        return TopKRegressionScenario(
            baseline=baseline,
            candidate=candidate,
            signal=signal,
            evidence=evidence,
        )

    @staticmethod
    def recovery_observation(
        *, window_start: datetime, window_seconds: int = 300
    ) -> RecoveryObservation:
        return RecoveryObservation(
            window_start=window_start,
            window_end=window_start + timedelta(seconds=window_seconds),
            observation_count=10,
            availability=0.999,
            error_rate=0.001,
            p95_latency_ms=295,
            guardrail_healthy=True,
            telemetry_complete=True,
            source_refs=["fault://top-k/recovery-window"],
        )

    def _measure(self, top_k: int) -> TopKMeasurement:
        retrieval = self._retrieval_base_ms + top_k * self._per_result_ms
        return TopKMeasurement(
            top_k=top_k,
            retrieval_p95_latency_ms=retrieval,
            model_p95_latency_ms=self._model_ms,
            agent_p95_latency_ms=retrieval + self._model_ms,
        )
