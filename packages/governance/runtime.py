"""Immediate policy enforcement wrappers for model and tool actions."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from agents.shared.model import ChatModel
from packages.contracts.governance import (
    DataClass,
    ModelInvocationAction,
    PolicyAgent,
    PolicyDecision,
    PolicyInput,
    PolicyRequestContext,
    PolicySubject,
    ToolAccess,
    ToolExecutionAction,
)
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    JsonValue,
    ModelRequest,
    ModelResponse,
    ToolDefinition,
    ToolObservation,
)
from packages.governance.engine import PolicyEngine, PolicyEngineUnavailable
from packages.governance.privacy import detect_pii, redact_model_request


@dataclass(frozen=True)
class RuntimePolicyContext:
    """Authenticated request facts propagated to nested model and tool calls."""

    subject: PolicySubject
    correlation_id: str
    release_id: str | None


_runtime_context: ContextVar[RuntimePolicyContext | None] = ContextVar(
    "agenthub_runtime_policy_context",
    default=None,
)


@contextmanager
def bind_policy_context(context: RuntimePolicyContext) -> Iterator[None]:
    """Bind caller attribution for one invocation and always restore prior state."""
    token = _runtime_context.set(context)
    try:
        yield
    finally:
        _runtime_context.reset(token)


class PolicyAuthorizer:
    """Build runtime policy inputs and fail closed on deny or engine outage."""

    def __init__(self, engine: PolicyEngine, agent: PolicyAgent, environment: str) -> None:
        self._engine = engine
        self._agent = agent
        self._environment = environment

    @property
    def external_model(self) -> bool:
        """Whether the declared provider is outside the local process."""
        return self._agent.model.provider != "fake"

    async def authorize_tool(
        self,
        *,
        tool_name: str,
        required_scopes: list[str],
        access: ToolAccess,
        arguments: dict[str, JsonValue],
    ) -> PolicyDecision:
        canonical = json.dumps(arguments, separators=(",", ":"), sort_keys=True)
        action = ToolExecutionAction(
            kind="tool_execution",
            tool_name=tool_name,
            required_scopes=required_scopes,
            access=access,
            arguments_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )
        return await self._authorize(action)

    async def authorize_model(
        self,
        request: ModelRequest,
        *,
        data_classes: list[DataClass] | None = None,
    ) -> PolicyDecision:
        provider = self._agent.model.provider
        model = self._agent.model.model
        input_characters = sum(len(message.content) for message in request.messages)
        action = ModelInvocationAction(
            kind="model_invocation",
            provider=provider,
            model=model,
            requested_input_tokens=max(1, (input_characters + 3) // 4),
            requested_output_tokens=request.max_tokens,
            data_classes=data_classes or [DataClass.INTERNAL],
            external_provider=provider != "fake",
        )
        return await self._authorize(action)

    async def _authorize(
        self,
        action: ModelInvocationAction | ToolExecutionAction,
    ) -> PolicyDecision:
        context = self._context()
        policy_input = PolicyInput(
            schema_version="agenthub.dev/policy-input/v1",
            subject=context.subject,
            agent=self._agent,
            action=action,
            context=PolicyRequestContext(
                environment=self._environment,
                correlation_id=context.correlation_id,
                occurred_at=datetime.now(UTC),
                release_id=context.release_id,
            ),
        )
        try:
            decision = await self._engine.decide(policy_input)
        except PolicyEngineUnavailable:
            raise AgentExecutionError(
                AgentErrorCode.POLICY_UNAVAILABLE,
                "Policy authorization is unavailable",
            ) from None
        if not decision.allow:
            raise AgentExecutionError(
                AgentErrorCode.POLICY_DENIED,
                "Action denied by policy",
            )
        return decision

    def _context(self) -> RuntimePolicyContext:
        context = _runtime_context.get()
        if context is not None:
            return context
        if self._environment in {"local", "test"}:
            return RuntimePolicyContext(
                subject=PolicySubject(
                    identity="local/internal",
                    kind="service",
                    authentication_method="local-explicit",
                    roles=["internal-runtime"],
                ),
                correlation_id="local-internal",
                release_id=None,
            )
        raise AgentExecutionError(
            AgentErrorCode.POLICY_DENIED,
            "Authenticated policy context is required",
        )


class AuthorizedChatModel:
    """Chat-model decorator that authorizes immediately before generation."""

    def __init__(self, target: ChatModel, authorizer: PolicyAuthorizer) -> None:
        self._target = target
        self._authorizer = authorizer

    @property
    def name(self) -> str:
        return self._target.name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        contains_pii = any(detect_pii(message.content) for message in request.messages)
        data_classes = [DataClass.INTERNAL]
        if contains_pii:
            data_classes.append(DataClass.PII)
        decision = await self._authorizer.authorize_model(
            request,
            data_classes=data_classes,
        )
        if contains_pii and self._authorizer.external_model:
            if not decision.obligations.redact_pii:
                raise AgentExecutionError(
                    AgentErrorCode.POLICY_DENIED,
                    "External PII handling denied by policy",
                )
            request = redact_model_request(request)
        return await self._target.generate(request)


class ToolTarget(Protocol):
    """Minimal callable surface wrapped by runtime tool authorization."""

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation: ...


class AuthorizedTool:
    """Tool decorator that authorizes immediately before invocation."""

    def __init__(
        self,
        target: ToolTarget,
        *,
        definition: ToolDefinition,
        authorizer: PolicyAuthorizer,
        required_scopes: list[str],
    ) -> None:
        self._target = target
        self.definition = definition
        self._authorizer = authorizer
        self._required_scopes = required_scopes

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        await self._authorizer.authorize_tool(
            tool_name=self.definition.name,
            required_scopes=self._required_scopes,
            access=ToolAccess.READ,
            arguments=arguments,
        )
        return await self._target.invoke(arguments)
