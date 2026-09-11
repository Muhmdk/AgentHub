"""Explainable, quality-constrained model routing tests."""

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import (
    CostRoutingPolicy,
    ModelCostProfile,
    RequestComplexity,
)
from packages.contracts.runtime import AgentRequest
from packages.delivery.cost_routing import (
    CostAwareModelRouter,
    CostRoutingBlockedError,
    RequestComplexityClassifier,
)


def _model(name: str, quality: float, input_cost: float, output_cost: float) -> ModelCostProfile:
    return ModelCostProfile(
        model=name,
        quality_score=quality,
        input_cost_per_million=input_cost,
        output_cost_per_million=output_cost,
    )


def _policy(*, small_quality: float = 0.85, large_quality: float = 0.95) -> CostRoutingPolicy:
    return CostRoutingPolicy(
        small_model=_model("azure/gpt-small", small_quality, 0.2, 0.8),
        large_model=_model("azure/gpt-large", large_quality, 2.0, 8.0),
        minimum_quality_score=0.8,
    )


def test_simple_request_selects_small_model_with_cost_and_reason() -> None:
    decision = CostAwareModelRouter.select(
        AgentRequest(query="What is our return policy?"),
        _policy(),
        requested_output_tokens=200,
    )

    assert decision.classification.complexity is RequestComplexity.SMALL
    assert decision.selected_model == "azure/gpt-small"
    assert decision.estimated_cost_usd < decision.alternative_cost_usd
    assert decision.estimated_savings_usd > 0
    assert "simple request" in decision.reason
    assert len(decision.classification.signals) == 6


def test_analytical_multi_entity_request_selects_large_model() -> None:
    request = AgentRequest(
        query="Compare Toronto and Vancouver inventory, analyze trade-offs, and return a table."
    )

    first = CostAwareModelRouter.select(request, _policy())
    replay = CostAwareModelRouter.select(request, _policy())

    assert replay == first
    assert first.classification.complexity is RequestComplexity.LARGE
    assert first.classification.score >= first.classification.threshold
    assert first.selected_model == "azure/gpt-large"
    assert first.estimated_savings_usd < 0
    assert "complex request" in first.reason


def test_small_model_below_quality_floor_falls_back_to_large() -> None:
    decision = CostAwareModelRouter.select(
        AgentRequest(query="Summarize the policy"),
        _policy(small_quality=0.7),
    )

    assert decision.selected_model == "azure/gpt-large"
    assert "misses the quality floor" in decision.reason


def test_no_appropriate_model_at_quality_floor_blocks_routing() -> None:
    with pytest.raises(CostRoutingBlockedError, match="below policy minimum"):
        CostAwareModelRouter.select(
            AgentRequest(query="Analyze and compare options in a sourced table"),
            _policy(large_quality=0.7),
        )


def test_disabled_cost_routing_uses_large_model() -> None:
    decision = CostAwareModelRouter.select(
        AgentRequest(query="Simple question"),
        _policy().model_copy(update={"enabled": False}),
    )

    assert decision.selected_model == "azure/gpt-large"
    assert "disabled" in decision.reason


def test_classifier_exposes_each_matched_signal() -> None:
    request = AgentRequest(query="Why this change? What differs between A vs. B? Include JSON.")

    assessment = RequestComplexityClassifier.classify(request)
    matched = {signal.name for signal in assessment.signals if signal.matched}

    assert matched == {"multiple_questions", "structured_output", "multiple_entities"}
    assert assessment.complexity is RequestComplexity.LARGE


def test_invalid_policy_and_request_limits_are_rejected() -> None:
    same_model = _model("azure/same", 0.9, 1, 1)
    with pytest.raises(ValidationError, match="must differ"):
        CostRoutingPolicy(small_model=same_model, large_model=same_model)
    with pytest.raises(ValueError, match="output tokens"):
        CostAwareModelRouter.select(
            AgentRequest(query="Hello"), _policy(), requested_output_tokens=0
        )
    with pytest.raises(ValueError, match="Complexity threshold"):
        RequestComplexityClassifier.classify(AgentRequest(query="Hello"), threshold=0)
