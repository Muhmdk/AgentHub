"""Policy-engine ports and local/OPA adapters."""

import asyncio
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from packages.contracts.governance import (
    DataClass,
    ModelInvocationAction,
    OPAQuery,
    OPAResponse,
    PolicyDecision,
    PolicyInput,
    PolicyObligations,
    ToolExecutionAction,
)


class PolicyEngineUnavailable(RuntimeError):
    """Policy engine failed or returned an invalid decision."""


class PolicyEngine(Protocol):
    """Asynchronous policy decision boundary."""

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision: ...


class LocalPolicyEngine:
    """Offline runtime policy evaluator for explicitly non-production use."""

    _VERSION = "local.phase08.1"

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        action = policy_input.action
        reasons: list[str]
        if isinstance(action, ToolExecutionAction):
            reasons = self._tool_denials(policy_input, action)
        elif isinstance(action, ModelInvocationAction):
            reasons = self._model_denials(policy_input, action)
        else:
            reasons = ["unsupported_action"]
        redact_pii = (
            isinstance(action, ModelInvocationAction)
            and action.external_provider
            and DataClass.PII in action.data_classes
        )
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=not reasons,
            reasons=reasons or [f"{action.kind}_allowed"],
            policy_bundle_version=self._VERSION,
            obligations=PolicyObligations(audit=True, redact_pii=redact_pii),
        )

    @staticmethod
    def _tool_denials(
        policy_input: PolicyInput,
        action: ToolExecutionAction,
    ) -> list[str]:
        named_grants = [
            grant for grant in policy_input.agent.tools if grant.name == action.tool_name
        ]
        if not named_grants:
            return ["tool_not_declared"]
        grants = [grant for grant in named_grants if grant.access == action.access]
        if not grants:
            return ["tool_access_not_allowed"]
        required = set(action.required_scopes)
        if not any(required.issubset(grant.scopes) for grant in grants):
            return ["missing_scope"]
        return []

    @staticmethod
    def _model_denials(
        policy_input: PolicyInput,
        action: ModelInvocationAction,
    ) -> list[str]:
        declared = policy_input.agent.model
        if action.provider != declared.provider or action.model != declared.model:
            return ["model_not_declared"]
        allowed_providers = {
            "local": {"fake"},
            "test": {"fake"},
            "staging": {"fake", "azure-openai"},
            "production": {"azure-openai"},
        }
        if action.provider not in allowed_providers[policy_input.context.environment.value]:
            return ["model_provider_not_allowed"]
        return []


class OPAHttpPolicyEngine:
    """Bounded client for OPA's versioned data API decision endpoint."""

    def __init__(self, url: str, timeout_seconds: float) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError("OPA URL must use HTTP or HTTPS")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("OPA timeout must be greater than zero and no more than 30 seconds")
        self._url = url
        self._timeout_seconds = timeout_seconds

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        return await asyncio.to_thread(self._request, policy_input)

    def _request(self, policy_input: PolicyInput) -> PolicyDecision:
        body = OPAQuery(input=policy_input).model_dump_json().encode()
        request = Request(
            self._url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
            return OPAResponse.model_validate(payload).result
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValidationError) as exc:
            raise PolicyEngineUnavailable("Policy engine is unavailable") from exc
