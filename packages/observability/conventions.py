"""AgentHub semantic conventions and their permitted telemetry surfaces."""

from enum import StrEnum


class Attribute(StrEnum):
    SERVICE_NAME = "service.name"
    SERVICE_VERSION = "service.version"
    DEPLOYMENT_ENVIRONMENT = "deployment.environment.name"
    HTTP_METHOD = "http.request.method"
    HTTP_ROUTE = "http.route"
    HTTP_STATUS_CODE = "http.response.status_code"
    AGENT_NAME = "agent.name"
    AGENT_VERSION = "agent.version"
    TEAM = "team.name"
    PROMPT_VERSION = "prompt.version"
    MODEL_PROVIDER = "model.provider"
    MODEL_DEPLOYMENT = "model.deployment"
    TOOL_NAME = "tool.name"
    RAG_CORPUS = "rag.corpus"
    RELEASE_ID = "release.id"
    CORRELATION_ID = "agenthub.correlation_id"
    ERROR_TYPE = "error.type"
    INPUT_TOKENS = "gen_ai.usage.input_tokens"
    OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    TOKEN_TYPE = "gen_ai.token.type"
    ESTIMATED_COST_USD = "agenthub.estimated_cost_usd"
    EVALUATION_SUITE = "evaluation.suite"
    EVALUATION_METRIC = "evaluation.metric"
    EVALUATION_GATE_PASSED = "evaluation.gate.passed"


SPAN_ATTRIBUTE_ALLOWLIST = frozenset(Attribute)

# Metric labels are deliberately smaller than span attributes. Request IDs, trace IDs,
# release IDs, errors, prompts, tool arguments, and retrieval queries are never labels.
METRIC_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        Attribute.HTTP_METHOD,
        Attribute.HTTP_ROUTE,
        Attribute.HTTP_STATUS_CODE,
        Attribute.AGENT_NAME,
        Attribute.AGENT_VERSION,
        Attribute.DEPLOYMENT_ENVIRONMENT,
        Attribute.TEAM,
        Attribute.MODEL_PROVIDER,
        Attribute.MODEL_DEPLOYMENT,
        Attribute.TOKEN_TYPE,
        Attribute.TOOL_NAME,
        Attribute.RAG_CORPUS,
        Attribute.EVALUATION_SUITE,
        Attribute.EVALUATION_METRIC,
        Attribute.EVALUATION_GATE_PASSED,
    }
)

METRIC_NAMES = frozenset(
    {
        "agenthub.http.requests",
        "agenthub.http.duration",
        "agenthub.agent.requests",
        "agenthub.agent.errors",
        "agenthub.agent.duration",
        "agenthub.tool.calls",
        "agenthub.tool.success",
        "agenthub.tool.duration",
        "agenthub.retrieval.duration",
        "agenthub.model.tokens",
        "agenthub.model.cost",
        "agenthub.evaluation.score",
        "agenthub.evaluation.gates",
        "agenthub.policy.denials",
    }
)
