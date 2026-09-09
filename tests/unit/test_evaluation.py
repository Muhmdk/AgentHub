"""Unit coverage for deterministic evaluators, runner bounds, and release gates."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.contracts.evaluation import (
    EvaluationDataset,
    EvaluationRunReport,
    EvaluationSuite,
    MetricAggregate,
)
from packages.contracts.runtime import AgentRequest, AgentResponse, Usage
from packages.evaluation.catalog import EvaluationCatalog, artifact_hash
from packages.evaluation.gates import decide_gate
from packages.evaluation.runner import EvaluationRunner

VERSION_ID = UUID("00000000-0000-0000-0000-000000000001")
RUN_ID = UUID("00000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


def response(answer: str = "safe answer") -> AgentResponse:
    return AgentResponse(
        answer=answer,
        model="fake/test",
        citations=[],
        tool_calls=[],
        usage=Usage(input_tokens=2, output_tokens=3, estimated_cost_usd=0),
    )


class RecordingTarget:
    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.delays = delays or {}
        self.active = 0
        self.max_active = 0

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(self.delays.get(request.query, 0))
            if request.query == "error":
                raise RuntimeError("private provider detail")
            return response(request.query)
        finally:
            self.active -= 1


def catalog_inputs() -> tuple[EvaluationSuite, EvaluationDataset]:
    suite, dataset, _ = EvaluationCatalog().resolve("knowledge-agent-suite")
    return suite, dataset


def run_target(
    target: RecordingTarget,
    suite: EvaluationSuite,
    dataset: EvaluationDataset,
) -> EvaluationRunReport:
    gate = EvaluationCatalog().gate_profile(suite.gate_profile_id)
    return asyncio.run(
        EvaluationRunner().run(
            target=target,
            agent_version_id=VERSION_ID,
            agent_version="1.0.0",
            manifest_hash="a" * 64,
            suite=suite,
            dataset=dataset,
            gate_profile=gate,
            environment="test",
            provider_settings={"provider": "fake"},
            run_id=RUN_ID,
            clock=lambda: NOW,
        )
    )


@pytest.mark.unit
def test_catalog_loads_versioned_inputs_and_hashes_canonically() -> None:
    suite, dataset, gate = EvaluationCatalog().resolve("knowledge-agent-suite")

    assert suite.dataset_id == dataset.dataset_id == "knowledge-agent"
    assert gate.profile_id == "default"
    assert artifact_hash({"b": 2, "a": 1}) == artifact_hash({"a": 1, "b": 2})


@pytest.mark.unit
def test_runner_preserves_case_order_and_bounds_concurrency() -> None:
    suite, source = catalog_inputs()
    cases = [
        source.cases[0].model_copy(
            update={
                "case_id": f"case-{index}",
                "request": AgentRequest(query=f"answer-{index}"),
                "expectations": source.cases[0].expectations.model_copy(
                    update={"exact_answer": f"answer-{index}", "citation_source_ids": []}
                ),
            }
        )
        for index in range(4)
    ]
    dataset = source.model_copy(update={"cases": cases})
    suite = suite.model_copy(update={"max_concurrency": 2})
    target = RecordingTarget({"answer-0": 0.04, "answer-1": 0.03})

    report = run_target(target, suite, dataset)

    assert [case.case_id for case in report.case_results] == [f"case-{i}" for i in range(4)]
    assert target.max_active == 2
    assert report.replay_key == run_target(RecordingTarget(), suite, dataset).replay_key


@pytest.mark.unit
def test_runner_times_out_and_keeps_partial_results() -> None:
    suite, source = catalog_inputs()
    cases = [
        source.cases[0].model_copy(
            update={
                "case_id": "slow",
                "request": AgentRequest(query="slow"),
            }
        ),
        source.cases[0].model_copy(
            update={
                "case_id": "error",
                "request": AgentRequest(query="error"),
            }
        ),
        source.cases[0].model_copy(
            update={
                "case_id": "success",
                "request": AgentRequest(query="safe answer"),
                "expectations": source.cases[0].expectations.model_copy(
                    update={"exact_answer": "safe answer", "citation_source_ids": []}
                ),
            }
        ),
    ]
    dataset = source.model_copy(update={"cases": cases})
    suite = suite.model_copy(update={"case_timeout_seconds": 0.01})

    report = run_target(RecordingTarget({"slow": 0.1}), suite, dataset)

    assert [case.status for case in report.case_results] == ["timeout", "error", "completed"]
    assert report.case_results[1].error_message == "Evaluation target failed"
    assert "private provider detail" not in report.model_dump_json()
    assert report.status == "failed"
    assert not report.gate.passed


@pytest.mark.unit
def test_gate_threshold_boundaries_and_relative_regression() -> None:
    profile = EvaluationCatalog().gate_profile("default")
    candidate = [
        MetricAggregate(
            name=name,
            evaluator_version="1.0.0",
            value=threshold.minimum if threshold.minimum is not None else threshold.maximum or 0,
            case_count=1,
            error_count=0,
        )
        for name, threshold in profile.thresholds.items()
    ]

    absolute = decide_gate(profile, candidate)
    baseline = [
        metric.model_copy(update={"value": 1000.0}) if metric.name == "p95_latency_ms" else metric
        for metric in candidate
    ]
    regressed = [
        metric.model_copy(update={"value": 1150.01}) if metric.name == "p95_latency_ms" else metric
        for metric in candidate
    ]
    relative = decide_gate(profile, regressed, baseline, RUN_ID)

    assert absolute.passed
    assert all(reason.passed for reason in absolute.reasons)
    assert not relative.passed
    assert any(reason.code == "regression_failed" for reason in relative.reasons)


@pytest.mark.unit
def test_gate_fails_closed_for_missing_or_errored_metric() -> None:
    profile = EvaluationCatalog().gate_profile("default")
    unavailable = MetricAggregate(
        name="correctness",
        evaluator_version="1.0.0",
        value=1.0,
        case_count=0,
        error_count=1,
    )

    decision = decide_gate(profile, [unavailable])

    assert not decision.passed
    assert all(reason.code == "metric_unavailable" for reason in decision.reasons)
