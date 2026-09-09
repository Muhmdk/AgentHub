"""Golden suites prove every demonstration agent clears deterministic gates."""

import asyncio
from uuid import UUID

import pytest

from agents.inventory.agent import InventoryAgent
from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from agents.shopping.agent import ShoppingAgent
from agents.shopping.tools import ProductSearchTool
from packages.evaluation.catalog import EvaluationCatalog
from packages.evaluation.runner import EvaluationRunner, EvaluationTarget


@pytest.mark.unit
@pytest.mark.parametrize("agent_name", ["inventory-agent", "knowledge-agent", "shopping-agent"])
def test_golden_agent_suite_passes(agent_name: str) -> None:
    retriever, corpus, _ = create_retail_retriever()
    targets: dict[str, EvaluationTarget] = {
        "inventory-agent": InventoryAgent(),
        "knowledge-agent": KnowledgeAgent(retriever=retriever, corpus=corpus),
        "shopping-agent": ShoppingAgent(product_tool=ProductSearchTool(retriever, corpus)),
    }
    suite, dataset, gate = EvaluationCatalog().resolve(f"{agent_name}-suite")

    report = asyncio.run(
        EvaluationRunner().run(
            target=targets[agent_name],
            agent_version_id=UUID("00000000-0000-0000-0000-000000000010"),
            agent_version="1.0.0",
            manifest_hash="a" * 64,
            suite=suite,
            dataset=dataset,
            gate_profile=gate,
            environment="golden-test",
            provider_settings={"provider": "fake"},
        )
    )

    assert report.status == "completed"
    assert report.gate.passed
    assert all(case.status == "completed" for case in report.case_results)
    assert all(reason.passed for reason in report.gate.reasons)
