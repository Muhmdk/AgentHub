"""Paired metric and uncertainty tests for shadow candidate comparisons."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import ResponseAssessment, ShadowPairRecord, ShadowStatus
from packages.contracts.runtime import AgentResponse, Usage
from packages.delivery.comparison import ShadowComparator

ROUTE_ID = UUID(int=10)
STABLE_ID = UUID(int=20)
CANDIDATE_ID = UUID(int=30)
NOW = datetime(2026, 9, 10, tzinfo=UTC)


def _response(answer: str, cost: float) -> AgentResponse:
    return AgentResponse(
        answer=answer,
        model="fake/deterministic-v1",
        citations=[],
        tool_calls=[],
        usage=Usage(input_tokens=10, output_tokens=5, estimated_cost_usd=cost),
    )


def _record(
    index: int,
    *,
    stable_answer: str = "stable-good",
    candidate_answer: str = "candidate-good",
    status: ShadowStatus = ShadowStatus.SUCCEEDED,
    stable_latency: float = 100,
    candidate_latency: float = 120,
    stable_cost: float = 0.01,
    candidate_cost: float = 0.015,
) -> ShadowPairRecord:
    return ShadowPairRecord(
        id=UUID(int=100 + index),
        correlation_id=f"pair-{index}",
        route_id=ROUTE_ID,
        route_revision=1 + index % 2,
        stable_release_id=STABLE_ID,
        candidate_release_id=CANDIDATE_ID,
        request_hash=f"{index + 1:x}" * 64,
        request_redacted=False,
        stable_response=_response(stable_answer, stable_cost),
        candidate_response=(
            _response(candidate_answer, candidate_cost)
            if status is ShadowStatus.SUCCEEDED
            else None
        ),
        shadow_status=status,
        shadow_error_code=None if status is ShadowStatus.SUCCEEDED else status.value,
        stable_latency_ms=stable_latency,
        shadow_latency_ms=candidate_latency,
        recorded_at=NOW + timedelta(minutes=index),
    )


class ScriptedScorer:
    def score(self, response: AgentResponse) -> ResponseAssessment:
        scores = {
            "stable-good": ResponseAssessment(quality=0.8, safety=0.95),
            "candidate-good": ResponseAssessment(quality=0.9, safety=0.98),
            "candidate-weak": ResponseAssessment(quality=0.6, safety=0.8),
        }
        return scores[response.answer]


def test_comparison_calculates_paired_quality_latency_error_safety_and_cost() -> None:
    records = [
        _record(0),
        _record(
            1,
            candidate_answer="candidate-weak",
            stable_latency=200,
            candidate_latency=250,
            candidate_cost=0.008,
        ),
        _record(
            2,
            status=ShadowStatus.TIMED_OUT,
            stable_latency=100,
            candidate_latency=110,
        ),
    ]

    report = ShadowComparator(ScriptedScorer()).compare(records)

    assert report.route_revisions == [1, 2]
    assert report.sample_count == 3
    assert report.successful_sample_count == 2
    assert report.quality.samples == 2
    assert report.quality.stable_mean == pytest.approx(0.8)
    assert report.quality.candidate_mean == pytest.approx(0.75)
    assert report.quality.delta == pytest.approx(-0.05)
    assert report.quality.confidence_low < report.quality.delta
    assert report.safety.delta == pytest.approx(-0.06)
    assert report.latency.delta == pytest.approx(80 / 3)
    assert report.error_rate.delta == pytest.approx(1 / 3)
    assert report.cost.delta == pytest.approx(0.0015)
    assert report.window_start == NOW
    assert report.window_end == NOW + timedelta(minutes=2)


def test_no_successful_candidates_report_zero_sample_quality_and_cost() -> None:
    report = ShadowComparator(ScriptedScorer()).compare([_record(0, status=ShadowStatus.FAILED)])

    assert report.successful_sample_count == 0
    assert report.quality.samples == 0
    assert report.quality.delta == 0
    assert report.cost.samples == 0
    assert report.error_rate.delta == 1


def test_comparison_rejects_empty_or_mixed_release_pairs() -> None:
    comparator = ShadowComparator(ScriptedScorer())

    with pytest.raises(ValueError, match="At least one"):
        comparator.compare([])
    with pytest.raises(ValueError, match="one route and release pairing"):
        comparator.compare(
            [
                _record(0),
                _record(1).model_copy(update={"candidate_release_id": UUID(int=31)}),
            ]
        )


def test_shadow_record_rejects_inconsistent_success_payload() -> None:
    with pytest.raises(ValidationError, match="Only successful"):
        ShadowPairRecord.model_validate(
            {**_record(0).model_dump(mode="python"), "candidate_response": None}
        )
