"""Bounded, timeout-aware evaluation runner with captured artifacts."""

import asyncio
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol, cast
from uuid import UUID, uuid4

from packages.contracts.evaluation import (
    CaseExecutionStatus,
    CaseMetricResult,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRunReport,
    EvaluationRunStatus,
    EvaluationSuite,
    GateProfile,
    MetricAggregate,
)
from packages.contracts.runtime import AgentExecutionError, AgentRequest, AgentResponse, JsonValue
from packages.evaluation.artifacts import report_artifact_hash
from packages.evaluation.catalog import EvaluationCatalog, artifact_hash
from packages.evaluation.evaluators import ModelJudge, evaluate_case
from packages.evaluation.gates import decide_gate


class EvaluationTarget(Protocol):
    async def invoke(self, request: AgentRequest) -> AgentResponse: ...


class EvaluationRunner:
    """Evaluate an agent without allowing one failed case to hide other results."""

    def __init__(self, model_judges: dict[str, ModelJudge] | None = None) -> None:
        self._model_judges = model_judges or {}

    async def run(
        self,
        *,
        target: EvaluationTarget,
        agent_version_id: UUID,
        agent_version: str,
        manifest_hash: str,
        suite: EvaluationSuite,
        dataset: EvaluationDataset,
        gate_profile: GateProfile,
        environment: str,
        provider_settings: dict[str, JsonValue],
        baseline_metrics: list[MetricAggregate] | None = None,
        baseline_run_id: UUID | None = None,
        run_id: UUID | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> EvaluationRunReport:
        if suite.dataset_id != dataset.dataset_id or suite.dataset_version != dataset.version:
            raise ValueError("Suite does not reference the supplied dataset")
        if dataset.agent_name != suite.suite_id.removesuffix("-suite"):
            raise ValueError("Suite and dataset target different agents")
        now = clock or (lambda: datetime.now(UTC))
        started_at = now()
        semaphore = asyncio.Semaphore(suite.max_concurrency)
        tasks = [
            asyncio.create_task(
                self._run_case(target, case, suite, semaphore),
                name=f"evaluation:{case.case_id}",
            )
            for case in dataset.cases
        ]
        try:
            case_results = list(await asyncio.gather(*tasks))
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        aggregates = self._aggregate(case_results, suite)
        gate = decide_gate(
            gate_profile,
            aggregates,
            baseline_metrics,
            baseline_run_id,
        )
        completed_at = now()
        status = (
            EvaluationRunStatus.FAILED
            if self._has_critical_error(case_results, suite)
            else EvaluationRunStatus.COMPLETED
        )
        catalog = EvaluationCatalog()
        dataset_hash = catalog.hash_model(dataset)
        suite_hash = catalog.hash_model(suite)
        gate_profile_hash = catalog.hash_model(gate_profile)
        replay_key = artifact_hash(
            {
                "agent_version_id": str(agent_version_id),
                "manifest_hash": manifest_hash,
                "dataset_hash": dataset_hash,
                "suite_hash": suite_hash,
                "gate_profile_hash": gate_profile_hash,
                "environment": environment,
                "provider_settings": provider_settings,
            }
        )
        report_values: dict[str, object] = {
            "run_id": run_id or uuid4(),
            "agent_name": dataset.agent_name,
            "agent_version": agent_version,
            "agent_version_id": agent_version_id,
            "manifest_hash": manifest_hash,
            "suite_id": suite.suite_id,
            "suite_version": suite.version,
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.version,
            "dataset_hash": dataset_hash,
            "suite_hash": suite_hash,
            "gate_profile_hash": gate_profile_hash,
            "environment": environment,
            "provider_settings": provider_settings,
            "started_at": started_at,
            "completed_at": completed_at,
            "status": status,
            "replay_key": replay_key,
            "case_results": case_results,
            "metrics": aggregates,
            "gate": gate,
        }
        report = EvaluationRunReport.model_validate({**report_values, "artifact_hash": "pending"})
        return report.model_copy(update={"artifact_hash": report_artifact_hash(report)})

    async def _run_case(
        self,
        target: EvaluationTarget,
        case: EvaluationCase,
        suite: EvaluationSuite,
        semaphore: asyncio.Semaphore,
    ) -> EvaluationCaseResult:
        started = perf_counter()
        async with semaphore:
            try:
                response = await asyncio.wait_for(
                    target.invoke(case.request),
                    timeout=suite.case_timeout_seconds,
                )
            except TimeoutError:
                return self._failed_case(
                    case,
                    suite,
                    CaseExecutionStatus.TIMEOUT,
                    started,
                    "case_timeout",
                    f"Case exceeded {suite.case_timeout_seconds:g}s timeout",
                )
            except AgentExecutionError as exc:
                return self._failed_case(
                    case,
                    suite,
                    CaseExecutionStatus.ERROR,
                    started,
                    exc.code.value,
                    exc.message,
                )
            except Exception:
                return self._failed_case(
                    case,
                    suite,
                    CaseExecutionStatus.ERROR,
                    started,
                    "target_error",
                    "Evaluation target failed",
                )

        latency_ms = (perf_counter() - started) * 1000
        metrics = await evaluate_case(
            case,
            response,
            latency_ms,
            suite.evaluators,
            self._model_judges,
        )
        values: dict[str, object] = {
            "case_id": case.case_id,
            "status": CaseExecutionStatus.COMPLETED,
            "input": case.request.model_dump(mode="json"),
            "output": response.model_dump(mode="json"),
            "latency_ms": latency_ms,
            "metrics": metrics,
            "error_code": None,
            "error_message": None,
        }
        return EvaluationCaseResult.model_validate(
            {**values, "artifact_hash": artifact_hash(_json_value(values))}
        )

    @staticmethod
    def _failed_case(
        case: EvaluationCase,
        suite: EvaluationSuite,
        status: CaseExecutionStatus,
        started: float,
        error_code: str,
        error_message: str,
    ) -> EvaluationCaseResult:
        metrics = [
            CaseMetricResult(
                name=spec.name,
                evaluator_version=spec.version,
                error=f"Case {status.value}: {error_code}",
            )
            for spec in suite.evaluators
        ]
        values: dict[str, object] = {
            "case_id": case.case_id,
            "status": status,
            "input": case.request.model_dump(mode="json"),
            "output": None,
            "latency_ms": (perf_counter() - started) * 1000,
            "metrics": metrics,
            "error_code": error_code,
            "error_message": error_message,
        }
        return EvaluationCaseResult.model_validate(
            {**values, "artifact_hash": artifact_hash(_json_value(values))}
        )

    @staticmethod
    def _aggregate(
        cases: list[EvaluationCaseResult], suite: EvaluationSuite
    ) -> list[MetricAggregate]:
        aggregates: list[MetricAggregate] = []
        for spec in suite.evaluators:
            matching = [
                metric
                for case in cases
                for metric in case.metrics
                if metric.name == spec.name and metric.evaluator_version == spec.version
            ]
            values = [metric.value for metric in matching if metric.value is not None]
            errors = sum(metric.error is not None for metric in matching)
            if spec.name == "p95_latency_ms" and values:
                ordered = sorted(values)
                value = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
            else:
                value = sum(values) / len(values) if values else 0.0
            aggregates.append(
                MetricAggregate(
                    name=spec.name,
                    evaluator_version=spec.version,
                    value=value,
                    case_count=len(values),
                    error_count=errors,
                )
            )
        return aggregates

    @staticmethod
    def _has_critical_error(cases: list[EvaluationCaseResult], suite: EvaluationSuite) -> bool:
        critical = {spec.name for spec in suite.evaluators if spec.critical}
        return any(
            metric.name in critical and metric.error is not None
            for case in cases
            for metric in case.metrics
        )


def _json_value(value: object) -> JsonValue:
    """Normalize UUIDs, datetimes, enums, and models before canonical hashing."""
    from pydantic_core import to_json

    return cast(JsonValue, json.loads(to_json(value)))
