"""Isolation, timeout, sampling, and redaction tests for shadow execution."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.contracts.delivery import (
    DeliveryEnvironment,
    RouteTarget,
    ShadowStatus,
    TrafficAllocation,
    TrafficRoute,
)
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    AgentRequest,
    AgentResponse,
    Citation,
    JsonValue,
    ToolDefinition,
    ToolObservation,
    Usage,
)
from packages.delivery.context import bind_shadow_execution
from packages.delivery.shadow import InMemoryShadowRecordSink, ShadowDispatcher
from packages.governance import AuthorizedTool, LocalPolicyEngine, PolicyAuthorizer
from packages.governance.profiles import agent_policy_profiles


def _response(answer: str) -> AgentResponse:
    return AgentResponse(
        answer=answer,
        model="fake/deterministic-v1",
        citations=[],
        tool_calls=[],
        usage=Usage(input_tokens=5, output_tokens=3, estimated_cost_usd=0.001),
    )


def _route() -> TrafficRoute:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    return TrafficRoute(
        id=UUID("a88eea69-a632-4fd7-a2ec-49690f9be064"),
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        allocation=TrafficAllocation(
            stable=RouteTarget(
                release_id=UUID(int=1),
                agent_version_id=UUID(int=11),
                agent_version="1.0.0",
                provenance_hash="a" * 64,
            ),
            candidate=RouteTarget(
                release_id=UUID(int=2),
                agent_version_id=UUID(int=12),
                agent_version="2.0.0",
                provenance_hash="b" * 64,
            ),
        ),
        revision=1,
        created_by="delivery-operator",
        created_at=now,
        updated_by="delivery-operator",
        updated_at=now,
    )


class RecordingAgent:
    def __init__(
        self,
        response: AgentResponse,
        *,
        delay_seconds: float = 0,
        failure: Exception | None = None,
    ) -> None:
        self.response = response
        self.delay_seconds = delay_seconds
        self.failure = failure
        self.requests: list[AgentRequest] = []
        self.cancelled = False

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.failure is not None:
            raise self.failure
        return self.response


def test_shadow_is_redacted_async_and_never_changes_stable_response() -> None:
    async def scenario() -> None:
        stable_response = _response("stable answer")
        stable = RecordingAgent(stable_response)
        candidate = RecordingAgent(_response("candidate answer"))
        sink = InMemoryShadowRecordSink()
        dispatcher = ShadowDispatcher(sink, timeout_seconds=0.1)
        request = AgentRequest(query="Email alex@example.com about policy")

        visible = await dispatcher.invoke(
            stable=stable,
            candidate=candidate,
            route=_route(),
            request=request,
            correlation_id="shadow-pair-1",
            sampling_key="subject-1",
        )
        assert visible is stable_response
        assert sink.records == []

        await dispatcher.drain()
        assert stable.requests == [request]
        assert candidate.requests[0].query == "Email [REDACTED:EMAIL] about policy"
        pair = sink.records[0]
        assert pair.stable_response.answer == "stable answer"
        assert pair.candidate_response is not None
        assert pair.candidate_response.answer == "candidate answer"
        assert pair.shadow_status is ShadowStatus.SUCCEEDED
        assert pair.request_redacted is True
        assert "alex@example.com" not in pair.model_dump_json()

    asyncio.run(scenario())


def test_shadow_timeout_cancels_candidate_and_records_only_safe_failure() -> None:
    async def scenario() -> None:
        stable = RecordingAgent(_response("stable answer"))
        candidate = RecordingAgent(_response("late answer"), delay_seconds=1)
        sink = InMemoryShadowRecordSink()
        dispatcher = ShadowDispatcher(sink, timeout_seconds=0.001)

        visible = await dispatcher.invoke(
            stable=stable,
            candidate=candidate,
            route=_route(),
            request=AgentRequest(query="Safe request"),
            correlation_id="shadow-timeout-1",
            sampling_key="subject-2",
        )
        await dispatcher.drain()

        assert visible.answer == "stable answer"
        assert candidate.cancelled is True
        assert sink.records[0].shadow_status is ShadowStatus.TIMED_OUT
        assert sink.records[0].candidate_response is None
        assert sink.records[0].shadow_error_code == AgentErrorCode.EXECUTION_TIMEOUT

    asyncio.run(scenario())


def test_shadow_failure_is_captured_without_affecting_stable() -> None:
    async def scenario() -> None:
        sink = InMemoryShadowRecordSink()
        dispatcher = ShadowDispatcher(sink)
        visible = await dispatcher.invoke(
            stable=RecordingAgent(_response("stable answer")),
            candidate=RecordingAgent(_response("unused"), failure=RuntimeError("secret detail")),
            route=_route(),
            request=AgentRequest(query="Safe request"),
            correlation_id="shadow-failure-1",
            sampling_key="subject-3",
        )
        await dispatcher.drain()

        assert visible.answer == "stable answer"
        assert sink.records[0].shadow_status is ShadowStatus.FAILED
        assert sink.records[0].shadow_error_code == "RuntimeError"
        assert "secret detail" not in sink.records[0].model_dump_json()

    asyncio.run(scenario())


def test_sampling_can_disable_candidate_without_changing_stable() -> None:
    async def scenario() -> None:
        candidate = RecordingAgent(_response("candidate answer"))
        sink = InMemoryShadowRecordSink()
        dispatcher = ShadowDispatcher(sink, sample_rate_basis_points=0)

        visible = await dispatcher.invoke(
            stable=RecordingAgent(_response("stable answer")),
            candidate=candidate,
            route=_route(),
            request=AgentRequest(query="Safe request"),
            correlation_id="shadow-unsampled-1",
            sampling_key="subject-4",
        )
        await dispatcher.drain()

        assert visible.answer == "stable answer"
        assert candidate.requests == []
        assert sink.records == []

    asyncio.run(scenario())


def test_cancelling_pending_shadow_cancels_candidate_and_records_evidence() -> None:
    async def scenario() -> None:
        candidate = RecordingAgent(_response("candidate answer"), delay_seconds=1)
        sink = InMemoryShadowRecordSink()
        dispatcher = ShadowDispatcher(sink, timeout_seconds=2)
        await dispatcher.invoke(
            stable=RecordingAgent(_response("stable answer")),
            candidate=candidate,
            route=_route(),
            request=AgentRequest(query="Safe request"),
            correlation_id="shadow-cancel-1",
            sampling_key="subject-5",
        )
        await asyncio.sleep(0)
        await dispatcher.cancel_pending()

        assert candidate.cancelled is True
        assert sink.records[0].shadow_status is ShadowStatus.CANCELLED

    asyncio.run(scenario())


class WriteTool:
    definition = ToolDefinition(
        name="orders.write",
        description="Create an order as a side effect",
        read_only=False,
    )

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        del arguments
        self.call_count += 1
        return ToolObservation(
            data={"created": True},
            citations=[Citation(source_id="order:test", title="Created order")],
        )


def test_shadow_write_tool_is_blocked_before_authorization_or_side_effect() -> None:
    target = WriteTool()
    profile = agent_policy_profiles("fake/deterministic-v1")["shopping-agent"]
    tool = AuthorizedTool(
        target,
        definition=target.definition,
        authorizer=PolicyAuthorizer(LocalPolicyEngine(), profile, "test"),
        required_scopes=["orders:write"],
    )

    with bind_shadow_execution(), pytest.raises(AgentExecutionError) as raised:
        asyncio.run(tool.invoke({"sku": "shovel"}))

    assert raised.value.code is AgentErrorCode.POLICY_DENIED
    assert target.call_count == 0


@pytest.mark.parametrize(
    ("sample_rate", "timeout"),
    [(-1, 1), (10_001, 1), (100, 0)],
)
def test_shadow_limits_are_validated(sample_rate: int, timeout: float) -> None:
    with pytest.raises(ValueError):
        ShadowDispatcher(
            InMemoryShadowRecordSink(),
            sample_rate_basis_points=sample_rate,
            timeout_seconds=timeout,
        )
