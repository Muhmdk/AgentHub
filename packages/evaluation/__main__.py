"""Run a registered agent evaluation and emit JSON or JUnit."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID
from xml.etree.ElementTree import Element, SubElement, tostring

from agents.inventory.agent import InventoryAgent
from agents.inventory.data import RetailData
from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from agents.shared.providers import create_chat_model, create_database, create_provider_bundle
from agents.shopping.agent import ShoppingAgent
from agents.shopping.tools import ProductSearchTool
from apps.api.config import load_settings
from packages.contracts.evaluation import EvaluationRunReport, RunEvaluationRequest
from packages.contracts.manifest import AgentManifest
from packages.evaluation.repository import EvaluationRepository
from packages.evaluation.runner import EvaluationTarget
from packages.evaluation.service import EvaluationService
from packages.registry.repository import RegistryNotFoundError, RegistryRepository

ROOT = Path(__file__).parents[2]


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Evaluate a registered AgentHub agent")
    command.add_argument("--agent", default="inventory-agent")
    command.add_argument("--version", default="1.0.0")
    command.add_argument("--suite")
    command.add_argument("--candidate-profile", choices=("default", "regressed"), default="default")
    command.add_argument("--baseline-run-id", type=UUID)
    command.add_argument("--replay-run-id", type=UUID)
    command.add_argument("--environment", default="local")
    command.add_argument("--format", choices=("json", "junit"), default="json")
    return command


def create_targets() -> dict[str, EvaluationTarget]:
    settings = load_settings()
    model = create_chat_model(settings.model_provider)
    retriever, corpus, _ = create_retail_retriever()
    return {
        "inventory-agent": InventoryAgent(
            data=RetailData.load(),
            model=model,
            max_steps=settings.agent_max_steps,
            tool_timeout_seconds=settings.tool_timeout_seconds,
            execution_timeout_seconds=settings.agent_timeout_seconds,
        ),
        "knowledge-agent": KnowledgeAgent(
            retriever=retriever,
            corpus=corpus,
            model=model,
            top_k=settings.rag_top_k,
            minimum_score=settings.rag_minimum_score,
            timeout_seconds=settings.retrieval_timeout_seconds,
        ),
        "shopping-agent": ShoppingAgent(
            product_tool=ProductSearchTool(retriever, corpus),
            model=model,
            timeout_seconds=settings.agent_timeout_seconds,
        ),
    }


def ensure_registered(repository: RegistryRepository, agent_name: str, version: str) -> None:
    try:
        repository.get_version(agent_name, version)
        return
    except RegistryNotFoundError:
        pass
    path = ROOT / "data" / "manifests" / f"{agent_name}-v{version.split('.')[0]}.json"
    if not path.is_file():
        raise RegistryNotFoundError(f"Manifest was not found for {agent_name}@{version}")
    repository.register(
        AgentManifest.model_validate_json(path.read_text()),
        actor="evaluation-cli",
        correlation_id=f"evaluation-cli-{agent_name}-{version}",
    )


def junit(report: EvaluationRunReport) -> str:
    failures = [reason for reason in report.gate.reasons if not reason.passed]
    suite = Element(
        "testsuite",
        name=f"{report.agent_name}:{report.suite_id}",
        tests=str(len(report.gate.reasons)),
        failures=str(len(failures)),
        errors=str(sum(case.status != "completed" for case in report.case_results)),
        timestamp=report.completed_at.isoformat(),
    )
    properties = SubElement(suite, "properties")
    for name, value in (
        ("run_id", str(report.run_id)),
        ("artifact_hash", report.artifact_hash),
        ("replay_key", report.replay_key),
    ):
        SubElement(properties, "property", name=name, value=value)
    for reason in report.gate.reasons:
        case = SubElement(suite, "testcase", name=reason.code, classname=reason.metric or "gate")
        if not reason.passed:
            failure = SubElement(case, "failure", message=reason.message)
            failure.text = reason.model_dump_json()
    return tostring(suite, encoding="unicode", xml_declaration=True)


async def run(arguments: argparse.Namespace) -> EvaluationRunReport:
    settings = load_settings()
    providers = create_provider_bundle(settings)
    database = create_database(settings, providers)
    try:
        store = EvaluationRepository(database)
        if arguments.replay_run_id is not None:
            return await asyncio.to_thread(store.get, arguments.replay_run_id)
        registry = RegistryRepository(database)
        ensure_registered(registry, arguments.agent, arguments.version)
        service = EvaluationService(
            registry=registry,
            store=store,
            targets=create_targets(),
        )
        return await service.run(
            RunEvaluationRequest(
                agent_name=arguments.agent,
                agent_version=arguments.version,
                suite_id=arguments.suite or f"{arguments.agent}-suite",
                candidate_profile=arguments.candidate_profile,
                baseline_run_id=arguments.baseline_run_id,
                environment=arguments.environment,
            )
        )
    finally:
        database.dispose()
        providers.close()


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        report = asyncio.run(run(arguments))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 1
    print(junit(report) if arguments.format == "junit" else report.model_dump_json(indent=2))
    return 0 if report.status == "completed" and report.gate.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
