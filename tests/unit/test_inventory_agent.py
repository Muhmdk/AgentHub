"""Graph tests for bounded deterministic Inventory Agent execution."""

import asyncio
from typing import ClassVar

import pytest

from agents.inventory.agent import InventoryAgent
from agents.inventory.data import Product, RetailData, RetailDataset, Store
from agents.inventory.tools import default_inventory_tools
from agents.shared.model import DeterministicFakeModel
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    AgentRequest,
    AgentResponse,
    JsonValue,
    ModelRequest,
    ModelResponse,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
    ToolObservation,
)

QUESTION = "Which Toronto stores may run low on snow shovels this weekend?"


def run(agent: InventoryAgent, request: AgentRequest | None = None) -> AgentResponse:
    return asyncio.run(agent.invoke(request or AgentRequest(query=QUESTION, seed=42)))


class FailingInventoryTool:
    definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="inventory.read",
        description="Fail deterministically for testing.",
    )

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        raise ToolExecutionError(
            self.definition.name,
            ToolErrorCode.DATA_ERROR,
            "Inventory data is unavailable",
        )


class SlowInventoryTool:
    definition: ClassVar[ToolDefinition] = ToolDefinition(
        name="inventory.read",
        description="Wait deterministically for testing.",
    )

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        await asyncio.sleep(0.1)
        return ToolObservation(data={"records": []}, citations=[])


class SlowModel(DeterministicFakeModel):
    async def generate(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(0.1)
        return await super().generate(request)


class FailingModel(DeterministicFakeModel):
    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("sensitive provider detail")


@pytest.fixture(scope="module")
def data() -> RetailData:
    return RetailData.load()


@pytest.mark.unit
def test_agent_answers_reference_scenario_with_real_citations(data: RetailData) -> None:
    response = run(InventoryAgent(data=data))

    assert response.model == "fake/deterministic-v1"
    assert "Queen Street may run low" in response.answer
    assert "York Mills is not currently at risk" in response.answer
    assert "about 20.4 projected weekend demand" in response.answer
    assert [evidence.tool_name for evidence in response.tool_calls] == [
        "inventory.read",
        "sales.read",
        "promotions.read",
        "weather.read",
    ]
    assert all(evidence.status == "success" for evidence in response.tool_calls)
    assert {citation.source_id for citation in response.citations} == {
        "inventory:store-tor-queen:snow-shovel:2026-09-08",
        "inventory:store-tor-york:snow-shovel:2026-09-08",
        "sales:store-tor-queen:snow-shovel:2026-w36",
        "sales:store-tor-york:snow-shovel:2026-w36",
        "promotion:promo-tor-snow-2026-09",
        "weather:toronto:2026-09-12:2026-09-13",
    }


@pytest.mark.unit
def test_agent_replays_identical_seeded_inputs(data: RetailData) -> None:
    agent = InventoryAgent(data=data)
    request = AgentRequest(query=QUESTION, seed=7)

    assert run(agent, request) == run(agent, request)


@pytest.mark.unit
def test_agent_rejects_unknown_locations_without_leaking_input(data: RetailData) -> None:
    unknown = "sensitive-unknown-place"

    with pytest.raises(AgentExecutionError) as raised:
        run(InventoryAgent(data=data), AgentRequest(query=f"Will shovels run low in {unknown}?"))

    assert raised.value.code == AgentErrorCode.INVALID_REQUEST
    assert unknown not in raised.value.message


@pytest.mark.unit
def test_agent_returns_insufficient_evidence_for_empty_valid_data() -> None:
    empty_data = RetailData(
        RetailDataset(
            stores=[Store(store_id="store-1", name="Empty Store", city="Toronto", province="ON")],
            products=[Product(sku="snow-shovel", name="Snow Shovel", aliases=["shovels"])],
            inventory=[],
            sales=[],
            promotions=[],
            weather=[],
        )
    )

    response = run(InventoryAgent(data=empty_data))

    assert response.answer == (
        "Insufficient inventory or sales evidence to assess Snow Shovel in Toronto."
    )
    assert response.citations == []
    assert all(evidence.status == "no_data" for evidence in response.tool_calls)


@pytest.mark.unit
def test_agent_normalizes_tool_errors(data: RetailData) -> None:
    tools = default_inventory_tools(data)
    tools["inventory.read"] = FailingInventoryTool()

    with pytest.raises(AgentExecutionError) as raised:
        run(InventoryAgent(data=data, tools=tools))

    assert raised.value.code == AgentErrorCode.TOOL_ERROR
    assert raised.value.message == "Inventory data is unavailable"


@pytest.mark.unit
def test_agent_enforces_per_tool_timeout(data: RetailData) -> None:
    tools = default_inventory_tools(data)
    tools["inventory.read"] = SlowInventoryTool()

    with pytest.raises(AgentExecutionError) as raised:
        run(InventoryAgent(data=data, tools=tools, tool_timeout_seconds=0.01))

    assert raised.value.code == AgentErrorCode.TOOL_TIMEOUT
    assert raised.value.message == "inventory.read timed out"


@pytest.mark.unit
def test_agent_enforces_total_execution_timeout(data: RetailData) -> None:
    with pytest.raises(AgentExecutionError) as raised:
        run(
            InventoryAgent(
                data=data,
                model=SlowModel(),
                tool_timeout_seconds=1,
                execution_timeout_seconds=0.05,
            )
        )

    assert raised.value.code == AgentErrorCode.EXECUTION_TIMEOUT


@pytest.mark.unit
def test_agent_enforces_step_limit(data: RetailData) -> None:
    with pytest.raises(AgentExecutionError) as raised:
        run(InventoryAgent(data=data, max_steps=2))

    assert raised.value.code == AgentErrorCode.STEP_LIMIT


@pytest.mark.unit
def test_agent_normalizes_model_failure_without_leaking_detail(data: RetailData) -> None:
    with pytest.raises(AgentExecutionError) as raised:
        run(InventoryAgent(data=data, model=FailingModel()))

    assert raised.value.code == AgentErrorCode.MODEL_ERROR
    assert "sensitive provider detail" not in raised.value.message


@pytest.mark.unit
def test_agent_rejects_nonpositive_execution_limits() -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        InventoryAgent(max_steps=0)
