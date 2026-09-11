"""Optional read-only LangGraph investigator with strict grounding validation."""

import asyncio
import re
from datetime import datetime
from typing import Protocol, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from packages.contracts.incident import (
    DraftNarrativeClaim,
    EvidenceCitation,
    IncidentInvestigationReport,
    InvestigatorDraft,
    InvestigatorRequest,
    NarrativeClaim,
)

_DIRECT_ACTUATION = re.compile(
    r"(?i)(?:\bkubectl\s|\bhelm\s+(?:upgrade|rollback|install)|"
    r"\bterraform\s+(?:apply|destroy)|\baz\s+aks\b|"
    r"\bcurl\b[^\n]{0,100}/api/v1/|\bbearer\s+|\bpassword\s*=)"
)


class InvestigatorOutputError(RuntimeError):
    """Generated investigator output violated its evidence-only contract."""


class IncidentSummaryModel(Protocol):
    """Narrow structured model boundary with no tools or actuation methods."""

    @property
    def name(self) -> str: ...

    async def summarize(self, request: InvestigatorRequest) -> InvestigatorDraft: ...


class InvestigatorState(TypedDict, total=False):
    request: InvestigatorRequest
    generated_at: datetime
    draft: InvestigatorDraft
    report: IncidentInvestigationReport


InvestigatorGraph = CompiledStateGraph[
    InvestigatorState, None, InvestigatorState, InvestigatorState
]


class LangGraphIncidentInvestigator:
    """Summarize supplied evidence and validate every generated claim before use."""

    def __init__(
        self,
        model: IncidentSummaryModel,
        *,
        timeout_seconds: float = 5,
        max_steps: int = 2,
    ) -> None:
        if timeout_seconds <= 0 or max_steps < 2:
            raise ValueError("Investigator limits must allow two positive bounded steps")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_steps = max_steps
        self._graph = self._build_graph()

    def _build_graph(self) -> InvestigatorGraph:
        builder = StateGraph(InvestigatorState)
        builder.add_node("summarize", self._summarize)
        builder.add_node("validate", self._validate)
        builder.add_edge(START, "summarize")
        builder.add_edge("summarize", "validate")
        builder.add_edge("validate", END)
        return builder.compile(name="incident-investigator")

    async def investigate(
        self,
        request: InvestigatorRequest,
        *,
        generated_at: datetime,
    ) -> IncidentInvestigationReport:
        if request.deterministic.incident_id != request.incident_id:
            raise ValueError("Deterministic analysis belongs to a different incident")
        if request.timeline.incident_id != request.incident_id:
            raise ValueError("Timeline belongs to a different incident")
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("Investigation timestamps must be timezone-aware")
        initial = InvestigatorState(request=request, generated_at=generated_at)
        try:
            result = cast(
                InvestigatorState,
                await asyncio.wait_for(
                    self._graph.ainvoke(
                        initial,
                        config={"recursion_limit": self._max_steps + 2},
                    ),
                    timeout=self._timeout_seconds,
                ),
            )
        except TimeoutError:
            raise InvestigatorOutputError("Incident investigator timed out") from None
        report = result.get("report")
        if report is None:
            raise InvestigatorOutputError("Incident investigator produced no validated report")
        return report

    async def _summarize(self, state: InvestigatorState) -> InvestigatorState:
        draft = await self._model.summarize(state["request"])
        return {**state, "draft": draft}

    def _validate(self, state: InvestigatorState) -> InvestigatorState:
        request = state["request"]
        draft = state.get("draft")
        if draft is None:
            raise InvestigatorOutputError("Incident investigator produced no draft")
        if request.deterministic.probable_cause is None and draft.probable_cause is not None:
            raise InvestigatorOutputError(
                "Generated probable cause is not supported by deterministic findings"
            )
        citations = {
            entry.entry_id: EvidenceCitation(
                evidence_id=entry.entry_id,
                source_ref=entry.source_ref,
                content_hash=entry.content_hash,
            )
            for entry in request.timeline.entries
        }
        generated_at = state["generated_at"]
        report = IncidentInvestigationReport(
            incident_id=request.incident_id,
            probable_cause=self._claim(draft.probable_cause, citations),
            observations=[self._required_claim(claim, citations) for claim in draft.observations],
            counter_evidence=[
                self._required_claim(claim, citations) for claim in draft.counter_evidence
            ],
            blast_radius=self._claim(draft.blast_radius, citations),
            recommended_action=draft.recommended_action,
            recommendation_rationale=self._required_claim(
                draft.recommendation_rationale, citations
            ),
            missing_evidence=request.deterministic.missing_evidence,
            generated_by=self._model.name,
            generated_at=generated_at,
        )
        return {**state, "report": report}

    @classmethod
    def _claim(
        cls,
        claim: DraftNarrativeClaim | None,
        citations: dict[UUID, EvidenceCitation],
    ) -> NarrativeClaim | None:
        return cls._required_claim(claim, citations) if claim is not None else None

    @staticmethod
    def _required_claim(
        claim: DraftNarrativeClaim,
        citations: dict[UUID, EvidenceCitation],
    ) -> NarrativeClaim:
        if _DIRECT_ACTUATION.search(claim.statement):
            raise InvestigatorOutputError("Generated claim contains a direct actuation path")
        unknown = [identifier for identifier in claim.citation_ids if identifier not in citations]
        if unknown:
            raise InvestigatorOutputError("Generated claim cites evidence that was not supplied")
        if not claim.citation_ids:
            raise InvestigatorOutputError("Generated claim is missing evidence citations")
        return NarrativeClaim(
            statement=claim.statement,
            uncertainty=claim.uncertainty,
            citations=[citations[identifier] for identifier in claim.citation_ids],
        )
