"""Immediate policy enforcement wrappers for model and tool actions."""

import asyncio
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agents.shared.model import ChatModel, RetryableModelError
from packages.contracts.governance import (
    DataClass,
    GovernanceAuditEvent,
    GovernanceAuditEventType,
    GovernanceAuditOutcome,
    ModelInvocationAction,
    PolicyAgent,
    PolicyDecision,
    PolicyInput,
    PolicyObligations,
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
from packages.delivery.context import ensure_shadow_tool_access
from packages.governance.budgets import (
    BudgetExceeded,
    BudgetKey,
    BudgetLimits,
    BudgetManager,
    RateLimitExceeded,
)
from packages.governance.engine import PolicyEngine
from packages.governance.privacy import detect_pii, redact_model_request
from packages.governance.repository import (
    GovernanceAuditStore,
    InMemoryGovernanceAuditStore,
)


@dataclass(frozen=True)
class RuntimePolicyContext:
    """Authenticated request facts propagated to nested model and tool calls."""

    subject: PolicySubject
    correlation_id: str
    release_id: str | None


@dataclass(frozen=True)
class PolicyAuthorization:
    """An allowed decision together with its sanitized reproducibility input."""

    policy_input: PolicyInput
    decision: PolicyDecision


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

    def __init__(
        self,
        engine: PolicyEngine,
        agent: PolicyAgent,
        environment: str,
        audit_store: GovernanceAuditStore | None = None,
    ) -> None:
        self._engine = engine
        self._agent = agent
        self._environment = environment
        self._audit_store = audit_store or InMemoryGovernanceAuditStore()

    @property
    def external_model(self) -> bool:
        """Whether the declared provider is outside the local process."""
        return self._agent.model.provider != "fake"

    @property
    def budget_key(self) -> BudgetKey:
        """Return stable dimensions for model rate/token/cost accounting."""
        return BudgetKey(
            agent_name=self._agent.name,
            agent_version=self._agent.version,
            provider=self._agent.model.provider,
            model=self._agent.model.model,
        )

    async def authorize_tool(
        self,
        *,
        tool_name: str,
        required_scopes: list[str],
        access: ToolAccess,
        arguments: dict[str, JsonValue],
    ) -> PolicyAuthorization:
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
    ) -> PolicyAuthorization:
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
    ) -> PolicyAuthorization:
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
        except Exception:
            await self._append_audit(
                policy_input,
                event_type=GovernanceAuditEventType.POLICY_DECISION,
                outcome=GovernanceAuditOutcome.POLICY_UNAVAILABLE,
                allowed=False,
                policy_bundle_version="unavailable",
                reasons=["policy_engine_unavailable"],
                obligations=PolicyObligations(),
            )
            raise AgentExecutionError(
                AgentErrorCode.POLICY_UNAVAILABLE,
                "Policy authorization is unavailable",
            ) from None
        await self._append_audit(
            policy_input,
            event_type=GovernanceAuditEventType.POLICY_DECISION,
            outcome=(
                GovernanceAuditOutcome.ALLOW if decision.allow else GovernanceAuditOutcome.DENY
            ),
            allowed=decision.allow,
            policy_bundle_version=decision.policy_bundle_version,
            reasons=decision.reasons,
            obligations=decision.obligations,
        )
        if not decision.allow:
            raise AgentExecutionError(
                AgentErrorCode.POLICY_DENIED,
                "Action denied by policy",
            )
        return PolicyAuthorization(policy_input=policy_input, decision=decision)

    async def record_enforcement(
        self,
        authorization: PolicyAuthorization,
        *,
        outcome: GovernanceAuditOutcome,
        reason: str,
    ) -> None:
        """Append a denied runtime control that follows an allowed policy decision."""
        await self._append_audit(
            authorization.policy_input,
            event_type=GovernanceAuditEventType.RUNTIME_ENFORCEMENT,
            outcome=outcome,
            allowed=False,
            policy_bundle_version=authorization.decision.policy_bundle_version,
            reasons=[reason],
            obligations=authorization.decision.obligations,
        )

    async def _append_audit(
        self,
        policy_input: PolicyInput,
        *,
        event_type: GovernanceAuditEventType,
        outcome: GovernanceAuditOutcome,
        allowed: bool,
        policy_bundle_version: str,
        reasons: list[str],
        obligations: PolicyObligations,
    ) -> None:
        event = GovernanceAuditEvent(
            id=uuid4(),
            event_type=event_type,
            outcome=outcome,
            allowed=allowed,
            identity=policy_input.subject.identity,
            agent_name=policy_input.agent.name,
            agent_version=policy_input.agent.version,
            action_kind=policy_input.action.kind,
            target=self._action_target(policy_input),
            policy_bundle_version=policy_bundle_version,
            reasons=reasons,
            obligations=obligations,
            occurred_at=datetime.now(UTC),
            correlation_id=policy_input.context.correlation_id,
            release_id=policy_input.context.release_id,
            sanitized_input=policy_input,
        )
        try:
            await asyncio.to_thread(self._audit_store.append, event)
        except Exception:
            raise AgentExecutionError(
                AgentErrorCode.POLICY_UNAVAILABLE,
                "Governance audit is unavailable",
            ) from None

    @staticmethod
    def _action_target(policy_input: PolicyInput) -> str:
        action = policy_input.action
        if isinstance(action, ModelInvocationAction):
            return f"{action.provider}/{action.model}"
        if isinstance(action, ToolExecutionAction):
            return action.tool_name
        if action.kind == "registration":
            return action.manifest_hash
        return action.target_environment.value

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

    def __init__(
        self,
        target: ChatModel,
        authorizer: PolicyAuthorizer,
        *,
        budget_manager: BudgetManager | None = None,
        budget_limits: BudgetLimits | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.05,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
    ) -> None:
        if (
            timeout_seconds <= 0
            or not 1 <= max_attempts <= 3
            or not 0 <= retry_backoff_seconds <= 5
            or input_cost_per_million < 0
            or output_cost_per_million < 0
        ):
            raise ValueError("Authorized model execution limits are invalid")
        self._target = target
        self._authorizer = authorizer
        self._budget_manager = budget_manager or BudgetManager()
        self._budget_limits = budget_limits or BudgetLimits()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._input_cost_per_million = input_cost_per_million
        self._output_cost_per_million = output_cost_per_million

    @property
    def name(self) -> str:
        return self._target.name

    async def generate(self, request: ModelRequest) -> ModelResponse:
        contains_pii = any(detect_pii(message.content) for message in request.messages)
        data_classes = [DataClass.INTERNAL]
        if contains_pii:
            data_classes.append(DataClass.PII)
        authorization = await self._authorizer.authorize_model(
            request,
            data_classes=data_classes,
        )
        decision = authorization.decision
        if contains_pii and self._authorizer.external_model:
            if not decision.obligations.redact_pii:
                raise AgentExecutionError(
                    AgentErrorCode.POLICY_DENIED,
                    "External PII handling denied by policy",
                )
            request = redact_model_request(request)
        input_tokens = max(
            1,
            (sum(len(message.content) for message in request.messages) + 3) // 4,
        )
        estimated_tokens = input_tokens + request.max_tokens
        estimated_cost = (
            input_tokens * self._input_cost_per_million
            + request.max_tokens * self._output_cost_per_million
        ) / 1_000_000
        policy_rate = decision.obligations.rate_limit_per_minute
        effective_limits = BudgetLimits(
            requests_per_minute=min(
                self._budget_limits.requests_per_minute,
                policy_rate or self._budget_limits.requests_per_minute,
            ),
            tokens_per_minute=self._budget_limits.tokens_per_minute,
            cost_per_hour_usd=self._budget_limits.cost_per_hour_usd,
        )
        try:
            lease = self._budget_manager.reserve(
                self._authorizer.budget_key,
                effective_limits,
                tokens=estimated_tokens,
                cost_usd=estimated_cost,
            )
        except RateLimitExceeded:
            await self._authorizer.record_enforcement(
                authorization,
                outcome=GovernanceAuditOutcome.RATE_LIMITED,
                reason="model_rate_limit_exceeded",
            )
            raise AgentExecutionError(
                AgentErrorCode.RATE_LIMITED,
                "Model rate limit exceeded",
            ) from None
        except BudgetExceeded:
            await self._authorizer.record_enforcement(
                authorization,
                outcome=GovernanceAuditOutcome.BUDGET_EXCEEDED,
                reason="model_budget_exceeded",
            )
            raise AgentExecutionError(
                AgentErrorCode.BUDGET_EXCEEDED,
                "Model budget exceeded",
            ) from None

        policy_timeout = decision.obligations.timeout_ms
        timeout_seconds = min(
            self._timeout_seconds,
            policy_timeout / 1000 if policy_timeout is not None else self._timeout_seconds,
        )
        try:
            response = await self._generate_with_retries(request, timeout_seconds)
        except BaseException:
            self._budget_manager.release(lease)
            raise
        self._budget_manager.complete(
            lease,
            tokens=response.usage.input_tokens + response.usage.output_tokens,
            cost_usd=response.usage.estimated_cost_usd,
        )
        return response

    async def _generate_with_retries(
        self,
        request: ModelRequest,
        timeout_seconds: float,
    ) -> ModelResponse:
        for attempt in range(self._max_attempts):
            try:
                return await asyncio.wait_for(
                    self._target.generate(request),
                    timeout=timeout_seconds,
                )
            except (RetryableModelError, TimeoutError) as exc:
                if attempt + 1 == self._max_attempts:
                    code = (
                        AgentErrorCode.MODEL_TIMEOUT
                        if isinstance(exc, TimeoutError)
                        else AgentErrorCode.MODEL_ERROR
                    )
                    message = (
                        "Model invocation timed out"
                        if code == AgentErrorCode.MODEL_TIMEOUT
                        else "Model provider is unavailable"
                    )
                    raise AgentExecutionError(code, message) from None
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
        raise AssertionError("Model retry loop completed without a result")


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
        access = ToolAccess.READ if self.definition.read_only else ToolAccess.WRITE
        ensure_shadow_tool_access(access)
        await self._authorizer.authorize_tool(
            tool_name=self.definition.name,
            required_scopes=self._required_scopes,
            access=access,
            arguments=arguments,
        )
        return await self._target.invoke(arguments)
