"""Paired statistical comparison of stable and shadow candidate responses."""

import math
from statistics import fmean, stdev
from typing import Protocol

from packages.contracts.delivery import (
    MetricDelta,
    ResponseAssessment,
    ShadowComparison,
    ShadowPairRecord,
    ShadowStatus,
)
from packages.contracts.runtime import AgentResponse


class ResponseScorer(Protocol):
    """Evaluate response quality and safety using a versioned external rubric."""

    def score(self, response: AgentResponse) -> ResponseAssessment: ...


class ShadowComparator:
    """Calculate paired deltas and uncertainty for a single release pairing."""

    def __init__(self, scorer: ResponseScorer) -> None:
        self._scorer = scorer

    def compare(self, records: list[ShadowPairRecord]) -> ShadowComparison:
        if not records:
            raise ValueError("At least one paired shadow record is required")
        self._validate_pair_identity(records)
        successful = [
            record
            for record in records
            if record.shadow_status is ShadowStatus.SUCCEEDED
            and record.candidate_response is not None
        ]

        stable_assessments = [self._scorer.score(record.stable_response) for record in successful]
        candidate_assessments = [
            self._scorer.score(record.candidate_response)
            for record in successful
            if record.candidate_response is not None
        ]
        first = records[0]
        timestamps = [record.recorded_at for record in records]
        return ShadowComparison(
            route_id=first.route_id,
            route_revisions=sorted({record.route_revision for record in records}),
            stable_release_id=first.stable_release_id,
            candidate_release_id=first.candidate_release_id,
            sample_count=len(records),
            successful_sample_count=len(successful),
            window_start=min(timestamps),
            window_end=max(timestamps),
            quality=self._metric(
                [assessment.quality for assessment in stable_assessments],
                [assessment.quality for assessment in candidate_assessments],
                unit="score",
                lower_is_better=False,
            ),
            safety=self._metric(
                [assessment.safety for assessment in stable_assessments],
                [assessment.safety for assessment in candidate_assessments],
                unit="score",
                lower_is_better=False,
            ),
            latency=self._metric(
                [record.stable_latency_ms for record in records],
                [record.shadow_latency_ms for record in records],
                unit="milliseconds",
                lower_is_better=True,
            ),
            error_rate=self._metric(
                [0.0 for _ in records],
                [
                    0.0 if record.shadow_status is ShadowStatus.SUCCEEDED else 1.0
                    for record in records
                ],
                unit="rate",
                lower_is_better=True,
            ),
            cost=self._metric(
                [record.stable_response.usage.estimated_cost_usd for record in successful],
                [
                    record.candidate_response.usage.estimated_cost_usd
                    for record in successful
                    if record.candidate_response is not None
                ],
                unit="usd",
                lower_is_better=True,
            ),
        )

    @staticmethod
    def _validate_pair_identity(records: list[ShadowPairRecord]) -> None:
        identities = {
            (record.route_id, record.stable_release_id, record.candidate_release_id)
            for record in records
        }
        if len(identities) != 1:
            raise ValueError("Shadow comparison records must share one route and release pairing")

    @staticmethod
    def _metric(
        stable: list[float],
        candidate: list[float],
        *,
        unit: str,
        lower_is_better: bool,
    ) -> MetricDelta:
        if len(stable) != len(candidate):
            raise ValueError("Metric samples must be paired")
        if not stable:
            return MetricDelta(
                samples=0,
                stable_mean=0,
                candidate_mean=0,
                delta=0,
                confidence_low=0,
                confidence_high=0,
                unit=unit,
                lower_is_better=lower_is_better,
            )

        deltas = [new - baseline for baseline, new in zip(stable, candidate, strict=True)]
        delta = fmean(deltas)
        margin = 0.0
        if len(deltas) > 1:
            margin = 1.96 * stdev(deltas) / math.sqrt(len(deltas))
        return MetricDelta(
            samples=len(deltas),
            stable_mean=fmean(stable),
            candidate_mean=fmean(candidate),
            delta=delta,
            confidence_low=delta - margin,
            confidence_high=delta + margin,
            unit=unit,
            lower_is_better=lower_is_better,
        )
