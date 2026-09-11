"""Bounded LangGraph workflow for synthetic inventory risk questions."""

import asyncio
from datetime import timedelta
from time import perf_counter
from typing import TypedDict, cast

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.inventory.data import RetailData
from agents.inventory.tools import (
    InventoryReadOutput,
    InventoryTool,
    PromotionsReadOutput,
    SalesReadOutput,
    WeatherReadOutput,
    default_inventory_tools,
)
from agents.shared.model import ChatModel, DeterministicFakeModel
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    AgentRequest,
    AgentResponse,
    ChatMessage,
    Citation,
    ModelRequest,
    ToolCall,
    ToolCallEvidence,
    ToolExecutionError,
    ToolObservation,
)
from packages.observability import Telemetry, noop_telemetry
from packages.observability.conventions import Attribute


class InventoryState(TypedDict, total=False):
    request: AgentRequest
    city: str
    sku: str
    tool_calls: list[ToolCall]
    observations: dict[str, ToolObservation]
    evidence: list[ToolCallEvidence]
    citations: list[Citation]
    steps: int
    response: AgentResponse


InventoryGraph = CompiledStateGraph[InventoryState, None, InventoryState, InventoryState]


class InventoryAgent:
    """Inspect one city/SKU question through a fixed, auditable graph."""

    def __init__(
        self,
        *,
        data: RetailData | None = None,
        model: ChatModel | None = None,
        tools: dict[str, InventoryTool] | None = None,
        max_steps: int = 3,
        tool_timeout_seconds: float = 1.0,
        execution_timeout_seconds: float = 5.0,
        telemetry: Telemetry | None = None,
    ) -> None:
        if max_steps < 1 or tool_timeout_seconds <= 0 or execution_timeout_seconds <= 0:
            raise ValueError("Agent execution limits must be positive")
        self._data = data or RetailData.load()
        self._model = model or DeterministicFakeModel()
        self._tools = tools or default_inventory_tools(self._data)
        self._max_steps = max_steps
        self._tool_timeout_seconds = tool_timeout_seconds
        self._execution_timeout_seconds = execution_timeout_seconds
        self._telemetry = telemetry or noop_telemetry()
        self._graph = self._build_graph()

    def _build_graph(self) -> InventoryGraph:
        builder = StateGraph(InventoryState)
        builder.add_node("plan", self._plan)
        builder.add_node("tools", self._invoke_tools)
        builder.add_node("respond", self._respond)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "tools")
        builder.add_edge("tools", "respond")
        builder.add_edge("respond", END)
        return builder.compile(name="inventory-agent")

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        """Run the graph within the configured total execution deadline."""
        attributes = {
            Attribute.AGENT_NAME: "inventory-agent",
            Attribute.AGENT_VERSION: "1.0.0",
            Attribute.PROMPT_VERSION: "1.0.0",
            Attribute.MODEL_PROVIDER: self._model.name.split("/", 1)[0],
            Attribute.MODEL_DEPLOYMENT: self._model.name,
        }
        started = perf_counter()
        success = False
        try:
            with (
                self._telemetry.span("agent.invoke", attributes),
                self._telemetry.span("agent.graph", attributes),
            ):
                response = await self._invoke_graph(request)
            success = True
            return response
        finally:
            self._telemetry.record_agent(
                attributes,
                (perf_counter() - started) * 1000,
                success=success,
            )

    async def _invoke_graph(self, request: AgentRequest) -> AgentResponse:
        try:
            result = cast(
                InventoryState,
                await asyncio.wait_for(
                    self._graph.ainvoke(
                        InventoryState(request=request, steps=0),
                        config={"recursion_limit": self._max_steps + 5},
                    ),
                    timeout=self._execution_timeout_seconds,
                ),
            )
        except TimeoutError:
            raise AgentExecutionError(
                AgentErrorCode.EXECUTION_TIMEOUT,
                "Inventory Agent execution timed out",
            ) from None
        except GraphRecursionError:
            raise AgentExecutionError(
                AgentErrorCode.STEP_LIMIT,
                "Inventory Agent exceeded its step limit",
            ) from None

        response = result.get("response")
        if response is None:
            raise AgentExecutionError(
                AgentErrorCode.MODEL_ERROR,
                "Inventory Agent completed without a response",
            )
        return response

    async def _plan(self, state: InventoryState) -> InventoryState:
        steps = self._next_step(state)
        request = state["request"]
        try:
            city = self._data.resolve_city(request.query)
            sku = self._data.resolve_sku(request.query)
        except LookupError:
            raise AgentExecutionError(
                AgentErrorCode.INVALID_REQUEST,
                "Ask about a supported city and product",
            ) from None

        days_until_saturday = (5 - request.as_of.weekday()) % 7
        weekend_start = request.as_of + timedelta(days=days_until_saturday)
        weekend_end = weekend_start + timedelta(days=1)
        sales_end = request.as_of - timedelta(days=1)
        sales_start = sales_end - timedelta(days=6)
        common = {"city": city, "sku": sku}
        calls = [
            ToolCall(call_id="tool-1", name="inventory.read", arguments=common),
            ToolCall(
                call_id="tool-2",
                name="sales.read",
                arguments={
                    **common,
                    "start_date": sales_start.isoformat(),
                    "end_date": sales_end.isoformat(),
                },
            ),
            ToolCall(
                call_id="tool-3",
                name="promotions.read",
                arguments={
                    **common,
                    "start_date": weekend_start.isoformat(),
                    "end_date": weekend_end.isoformat(),
                },
            ),
            ToolCall(
                call_id="tool-4",
                name="weather.read",
                arguments={
                    "city": city,
                    "start_date": weekend_start.isoformat(),
                    "end_date": weekend_end.isoformat(),
                },
            ),
        ]
        return {**state, "city": city, "sku": sku, "tool_calls": calls, "steps": steps}

    async def _invoke_tools(self, state: InventoryState) -> InventoryState:
        steps = self._next_step(state)
        observations: dict[str, ToolObservation] = {}
        evidence: list[ToolCallEvidence] = []
        citations: list[Citation] = []

        for call in state["tool_calls"]:
            tool = self._tools.get(call.name)
            if tool is None:
                raise AgentExecutionError(
                    AgentErrorCode.TOOL_ERROR,
                    "Inventory Agent requested an undeclared tool",
                )
            attributes = {
                Attribute.AGENT_NAME: "inventory-agent",
                Attribute.AGENT_VERSION: "1.0.0",
                Attribute.TOOL_NAME: call.name,
            }
            started = perf_counter()
            success = False
            try:
                with self._telemetry.span("tool.invoke", attributes):
                    try:
                        observation = await asyncio.wait_for(
                            tool.invoke(call.arguments), timeout=self._tool_timeout_seconds
                        )
                    except TimeoutError:
                        raise AgentExecutionError(
                            AgentErrorCode.TOOL_TIMEOUT,
                            f"{call.name} timed out",
                        ) from None
                    except ToolExecutionError as exc:
                        raise AgentExecutionError(AgentErrorCode.TOOL_ERROR, exc.message) from None
                success = True
            finally:
                self._telemetry.record_tool(
                    attributes,
                    (perf_counter() - started) * 1000,
                    success=success,
                )

            observations[call.name] = observation
            citations.extend(observation.citations)
            evidence.append(
                ToolCallEvidence(
                    call_id=call.call_id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    source_ids=[citation.source_id for citation in observation.citations],
                    status="success" if observation.citations else "no_data",
                )
            )

        unique_citations = list({citation.source_id: citation for citation in citations}.values())
        return {
            **state,
            "observations": observations,
            "evidence": evidence,
            "citations": unique_citations,
            "steps": steps,
        }

    async def _respond(self, state: InventoryState) -> InventoryState:
        steps = self._next_step(state)
        draft = self._build_answer(state)
        request = ModelRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "Return only the supplied evidence-based answer. "
                        "Do not add hidden reasoning."
                    ),
                ),
                ChatMessage(role="user", content=f"FINAL_ANSWER:\n{draft}"),
            ],
            temperature=0.0,
            max_tokens=800,
            seed=state["request"].seed,
        )
        attributes = {
            Attribute.AGENT_NAME: "inventory-agent",
            Attribute.AGENT_VERSION: "1.0.0",
            Attribute.PROMPT_VERSION: "1.0.0",
            Attribute.MODEL_PROVIDER: self._model.name.split("/", 1)[0],
            Attribute.MODEL_DEPLOYMENT: self._model.name,
        }
        try:
            with self._telemetry.span("model.generate", attributes):
                model_response = await self._model.generate(request)
        except AgentExecutionError:
            raise
        except Exception as exc:
            raise AgentExecutionError(
                AgentErrorCode.MODEL_ERROR,
                "Inventory Agent model generation failed",
            ) from exc
        self._telemetry.record_model(
            attributes,
            input_tokens=model_response.usage.input_tokens,
            output_tokens=model_response.usage.output_tokens,
            cost_usd=model_response.usage.estimated_cost_usd,
        )

        response = AgentResponse(
            answer=model_response.content,
            model=model_response.model,
            citations=state["citations"],
            tool_calls=state["evidence"],
            usage=model_response.usage,
        )
        return {**state, "response": response, "steps": steps}

    def _build_answer(self, state: InventoryState) -> str:
        observations = state["observations"]
        inventory = InventoryReadOutput.model_validate(observations["inventory.read"].data)
        sales = SalesReadOutput.model_validate(observations["sales.read"].data)
        promotions = PromotionsReadOutput.model_validate(observations["promotions.read"].data)
        weather = WeatherReadOutput.model_validate(observations["weather.read"].data)

        if not inventory.records or not sales.records:
            product_name = self._data.product_name(state["sku"])
            return (
                f"Insufficient inventory or sales evidence to assess {product_name} in "
                f"{state['city']}."
            )

        promotion_lift = max(
            (promotion.demand_lift for promotion in promotions.records), default=1.0
        )
        weather_lift = max((forecast.demand_lift for forecast in weather.records), default=1.0)
        sales_by_store = {history.store_id: history for history in sales.records}
        assessments: list[tuple[bool, str]] = []
        product_name = self._data.product_name(state["sku"])

        for record in inventory.records:
            history = sales_by_store.get(record.store_id)
            if history is None:
                assessments.append(
                    (
                        True,
                        f"{record.store_name} has insufficient sales evidence for {product_name}.",
                    )
                )
                continue
            average_daily_sales = sum(history.daily_units) / len(history.daily_units)
            projected_demand = round(average_daily_sales * 2 * promotion_lift * weather_lift, 1)
            projected_remaining = record.on_hand - projected_demand
            at_risk = projected_remaining < record.reorder_point
            status = "may run low" if at_risk else "is not currently at risk"
            assessments.append(
                (
                    at_risk,
                    f"{record.store_name} {status}: {record.on_hand} {product_name} units on hand, "
                    f"about {projected_demand:g} projected weekend demand, and a "
                    f"{record.reorder_point} unit reorder point.",
                )
            )

        assessments.sort(key=lambda assessment: not assessment[0])
        return " ".join(message for _, message in assessments)

    def _next_step(self, state: InventoryState) -> int:
        next_step = state.get("steps", 0) + 1
        if next_step > self._max_steps:
            raise AgentExecutionError(
                AgentErrorCode.STEP_LIMIT,
                "Inventory Agent exceeded its step limit",
            )
        return next_step
