"""Explainable request complexity and quality-constrained model routing."""

import re

from packages.contracts.delivery import (
    ComplexityAssessment,
    ComplexitySignal,
    CostRouteDecision,
    CostRoutingPolicy,
    ModelCostProfile,
    RequestComplexity,
)
from packages.contracts.runtime import AgentRequest

_ANALYTICAL = re.compile(
    r"\b(analy[sz]e|compare|contrast|forecast|optimi[sz]e|trade[ -]?offs?|root cause)\b",
    re.IGNORECASE,
)
_STRUCTURED = re.compile(
    r"\b(table|json|schema|step[ -]?by[ -]?step|citations?|sources?)\b",
    re.IGNORECASE,
)
_MULTI_ENTITY = re.compile(r"\b(and|versus|vs\.?|across|between)\b", re.IGNORECASE)


class CostRoutingBlockedError(RuntimeError):
    """No model appropriate for the request meets the policy quality floor."""


class RequestComplexityClassifier:
    """Classify requests with stable lexical and structural signals."""

    @staticmethod
    def classify(request: AgentRequest, *, threshold: int = 3) -> ComplexityAssessment:
        if not 1 <= threshold <= 100:
            raise ValueError("Complexity threshold must be between 1 and 100")
        query = request.query
        question_count = query.count("?")
        signals = [
            ComplexitySignal(
                name="long_context",
                matched=len(query) > 600,
                weight=2,
                explanation="Request exceeds 600 characters",
            ),
            ComplexitySignal(
                name="medium_context",
                matched=200 < len(query) <= 600,
                weight=1,
                explanation="Request is between 201 and 600 characters",
            ),
            ComplexitySignal(
                name="multiple_questions",
                matched=question_count > 1,
                weight=1,
                explanation="Request contains multiple explicit questions",
            ),
            ComplexitySignal(
                name="analytical_intent",
                matched=_ANALYTICAL.search(query) is not None,
                weight=2,
                explanation="Request asks for analysis, comparison, or optimization",
            ),
            ComplexitySignal(
                name="structured_output",
                matched=_STRUCTURED.search(query) is not None,
                weight=1,
                explanation="Request requires structured or sourced output",
            ),
            ComplexitySignal(
                name="multiple_entities",
                matched=_MULTI_ENTITY.search(query) is not None,
                weight=1,
                explanation="Request relates multiple entities or dimensions",
            ),
        ]
        score = sum(signal.weight for signal in signals if signal.matched)
        complexity = RequestComplexity.LARGE if score >= threshold else RequestComplexity.SMALL
        matched_names = [signal.name for signal in signals if signal.matched]
        detail = ", ".join(matched_names) if matched_names else "no complexity signals"
        return ComplexityAssessment(
            complexity=complexity,
            score=score,
            threshold=threshold,
            signals=signals,
            reason=f"Classified as {complexity.value} at score {score}: {detail}",
        )


class CostAwareModelRouter:
    """Choose the least costly policy-permitted model for the classified request."""

    @staticmethod
    def select(
        request: AgentRequest,
        policy: CostRoutingPolicy,
        *,
        requested_output_tokens: int = 800,
    ) -> CostRouteDecision:
        if not 1 <= requested_output_tokens <= 100_000:
            raise ValueError("Requested output tokens must be between 1 and 100000")
        classification = RequestComplexityClassifier.classify(
            request, threshold=policy.complexity_threshold
        )
        selected = policy.large_model
        reason = "Large model selected because cost-aware routing is disabled"
        if policy.enabled and classification.complexity is RequestComplexity.SMALL:
            if policy.small_model.quality_score >= policy.minimum_quality_score:
                selected = policy.small_model
                reason = "Small model selected for a simple request within the quality floor"
            else:
                reason = "Large model selected because the small model misses the quality floor"
        elif policy.enabled:
            reason = "Large model selected for a complex request"

        if selected.quality_score < policy.minimum_quality_score:
            raise CostRoutingBlockedError(
                f"Selected model quality {selected.quality_score:.3f} is below policy minimum "
                f"{policy.minimum_quality_score:.3f}"
            )
        alternative = (
            policy.large_model if selected.model == policy.small_model.model else policy.small_model
        )
        input_tokens = max(1, (len(request.query) + 3) // 4)
        selected_cost = CostAwareModelRouter._estimated_cost(
            selected, input_tokens, requested_output_tokens
        )
        alternative_cost = CostAwareModelRouter._estimated_cost(
            alternative, input_tokens, requested_output_tokens
        )
        return CostRouteDecision(
            selected_model=selected.model,
            selected_quality_score=selected.quality_score,
            classification=classification,
            estimated_input_tokens=input_tokens,
            requested_output_tokens=requested_output_tokens,
            estimated_cost_usd=selected_cost,
            alternative_model=alternative.model,
            alternative_cost_usd=alternative_cost,
            estimated_savings_usd=alternative_cost - selected_cost,
            reason=reason,
        )

    @staticmethod
    def _estimated_cost(profile: ModelCostProfile, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * profile.input_cost_per_million
            + output_tokens * profile.output_cost_per_million
        ) / 1_000_000
