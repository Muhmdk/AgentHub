"""PostgreSQL coverage for immutable evaluation artifacts and replay."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError

from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from packages.contracts.evaluation import EvaluationRunReport
from packages.contracts.manifest import AgentManifest
from packages.evaluation.catalog import EvaluationCatalog
from packages.evaluation.models import (
    EvaluationCaseRecord,
    EvaluationGateRecord,
    EvaluationMetricRecord,
)
from packages.evaluation.repository import EvaluationConflictError, EvaluationRepository
from packages.evaluation.runner import EvaluationRunner
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository

ROOT = Path(__file__).parents[2]


def build_report(database: Database) -> EvaluationRunReport:
    manifest = AgentManifest.model_validate_json(
        (ROOT / "data/manifests/knowledge-agent-v1.json").read_text()
    )
    registered = RegistryRepository(database).register(
        manifest,
        actor="evaluation-test",
        correlation_id="evaluation-registration",
    )
    suite, dataset, gate = EvaluationCatalog().resolve("knowledge-agent-suite")
    retriever, corpus, _ = create_retail_retriever()
    return asyncio.run(
        EvaluationRunner().run(
            target=KnowledgeAgent(retriever=retriever, corpus=corpus),
            agent_version_id=registered.agent_version.id,
            agent_version=registered.agent_version.version,
            manifest_hash=registered.agent_version.manifest_hash,
            suite=suite,
            dataset=dataset,
            gate_profile=gate,
            environment="integration",
            provider_settings={"provider": "fake", "model": "deterministic-v1"},
        )
    )


@pytest.mark.integration
def test_evaluation_migration_created_normalized_artifact_tables(
    registry_database: Database,
) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())

    assert {
        "evaluation_runs",
        "evaluation_case_results",
        "evaluation_metrics",
        "evaluation_gate_decisions",
    } <= tables


@pytest.mark.integration
def test_report_round_trips_with_cases_metrics_and_gate(
    registry_database: Database,
) -> None:
    report = build_report(registry_database)
    repository = EvaluationRepository(registry_database)

    saved = repository.save(report)
    replayed = repository.get(report.run_id)

    assert saved == replayed == report
    assert repository.save(report) == report
    assert repository.list("knowledge-agent")[0].artifact_hash == report.artifact_hash
    with registry_database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationCaseRecord)) == 3
        assert session.scalar(select(func.count()).select_from(EvaluationMetricRecord)) == 10
        assert session.scalar(select(func.count()).select_from(EvaluationGateRecord)) == 1


@pytest.mark.integration
def test_evaluation_artifacts_are_immutable_and_conflicts_are_rejected(
    registry_database: Database,
) -> None:
    report = build_report(registry_database)
    repository = EvaluationRepository(registry_database)
    repository.save(report)

    with (
        pytest.raises(DBAPIError, match="evaluation artifacts are immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE evaluation_runs SET environment = 'tampered' WHERE id = :id"),
            {"id": report.run_id},
        )

    changed = report.model_copy(update={"artifact_hash": "b" * 64})
    with pytest.raises(EvaluationConflictError, match="different artifact"):
        repository.save(changed)
