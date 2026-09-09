"""Transactional persistence for immutable evaluation reports."""

from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.contracts.evaluation import EvaluationRunReport, EvaluationRunSummary
from packages.evaluation.models import (
    EvaluationCaseRecord,
    EvaluationGateRecord,
    EvaluationMetricRecord,
    EvaluationRunRecord,
)
from packages.registry.database import Database
from packages.registry.models import AgentVersionRecord


class EvaluationNotFoundError(RuntimeError):
    """Requested evaluation run does not exist."""


class EvaluationConflictError(RuntimeError):
    """An immutable evaluation artifact conflicts with stored data."""


class EvaluationStore(Protocol):
    def save(self, report: EvaluationRunReport) -> EvaluationRunReport: ...

    def get(self, run_id: UUID) -> EvaluationRunReport: ...

    def list(self, agent_name: str | None = None) -> list[EvaluationRunSummary]: ...


class EvaluationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def save(self, report: EvaluationRunReport) -> EvaluationRunReport:
        try:
            with self._database.transaction() as session:
                existing = session.get(EvaluationRunRecord, report.run_id)
                if existing is not None:
                    if existing.artifact_hash != report.artifact_hash:
                        raise EvaluationConflictError(
                            "Evaluation run already exists with a different artifact"
                        )
                    return self._report(existing)
                version = session.get(AgentVersionRecord, report.agent_version_id)
                if version is None:
                    raise EvaluationNotFoundError("Agent version was not found")
                if (
                    version.version != report.agent_version
                    or version.manifest_hash != report.manifest_hash
                ):
                    raise EvaluationConflictError(
                        "Evaluation report does not match its immutable agent version"
                    )

                session.add(
                    EvaluationRunRecord(
                        id=report.run_id,
                        agent_version_id=report.agent_version_id,
                        manifest_hash=report.manifest_hash,
                        suite_id=report.suite_id,
                        suite_version=report.suite_version,
                        dataset_id=report.dataset_id,
                        dataset_version=report.dataset_version,
                        dataset_hash=report.dataset_hash,
                        suite_hash=report.suite_hash,
                        gate_profile_hash=report.gate_profile_hash,
                        environment=report.environment,
                        provider_settings=report.provider_settings,
                        started_at=report.started_at,
                        completed_at=report.completed_at,
                        status=report.status.value,
                        replay_key=report.replay_key,
                        gate_passed=report.gate.passed,
                        artifact_hash=report.artifact_hash,
                        report=report.model_dump(mode="json"),
                    )
                )
                session.flush()
                session.add_all(
                    [
                        EvaluationCaseRecord(
                            id=uuid4(),
                            evaluation_run_id=report.run_id,
                            case_id=case.case_id,
                            status=case.status.value,
                            input=case.input,
                            output=case.output,
                            latency_ms=case.latency_ms,
                            metrics=[metric.model_dump(mode="json") for metric in case.metrics],
                            error_code=case.error_code,
                            error_message=case.error_message,
                            artifact_hash=case.artifact_hash,
                        )
                        for case in report.case_results
                    ]
                )
                session.add_all(
                    [
                        EvaluationMetricRecord(
                            id=uuid4(),
                            evaluation_run_id=report.run_id,
                            name=metric.name,
                            evaluator_version=metric.evaluator_version,
                            value=metric.value,
                            case_count=metric.case_count,
                            error_count=metric.error_count,
                        )
                        for metric in report.metrics
                    ]
                )
                session.add(
                    EvaluationGateRecord(
                        id=uuid4(),
                        evaluation_run_id=report.run_id,
                        passed=report.gate.passed,
                        profile_id=report.gate.profile_id,
                        profile_version=report.gate.profile_version,
                        baseline_run_id=report.gate.baseline_run_id,
                        reasons=[reason.model_dump(mode="json") for reason in report.gate.reasons],
                    )
                )
                session.flush()
                return report
        except IntegrityError as exc:
            raise EvaluationConflictError("Evaluation report violates immutable storage") from exc

    def get(self, run_id: UUID) -> EvaluationRunReport:
        with self._database.transaction() as session:
            record = session.get(EvaluationRunRecord, run_id)
            if record is None:
                raise EvaluationNotFoundError("Evaluation run was not found")
            return self._report(record)

    def list(self, agent_name: str | None = None) -> list[EvaluationRunSummary]:
        with self._database.transaction() as session:
            statement = select(EvaluationRunRecord, AgentVersionRecord).join(
                AgentVersionRecord,
                AgentVersionRecord.id == EvaluationRunRecord.agent_version_id,
            )
            if agent_name is not None:
                from packages.registry.models import AgentRecord

                statement = statement.join(
                    AgentRecord, AgentRecord.id == AgentVersionRecord.agent_id
                ).where(AgentRecord.name == agent_name)
            rows = session.execute(statement.order_by(EvaluationRunRecord.started_at.desc())).all()
            return [self._summary(run, version) for run, version in rows]

    @staticmethod
    def _report(record: EvaluationRunRecord) -> EvaluationRunReport:
        return EvaluationRunReport.model_validate(record.report)

    @staticmethod
    def _summary(run: EvaluationRunRecord, version: AgentVersionRecord) -> EvaluationRunSummary:
        report = EvaluationRunReport.model_validate(run.report)
        return EvaluationRunSummary(
            run_id=run.id,
            agent_name=report.agent_name,
            agent_version=version.version,
            suite_id=run.suite_id,
            suite_version=run.suite_version,
            status=report.status,
            gate_passed=run.gate_passed,
            started_at=run.started_at,
            completed_at=run.completed_at,
            artifact_hash=run.artifact_hash,
        )
