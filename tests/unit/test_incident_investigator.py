"""Citation and safety validation for the optional LangGraph investigator."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from packages.contracts.incident import (
    DeterministicInvestigation,
    DraftNarrativeClaim,
    EvidenceCitation,
    FindingKind,
    IncidentSeverity,
    IncidentTrigger,
    IncidentTriggerType,
    InvestigationClaim,
    InvestigatorDraft,
    InvestigatorRequest,
    RecommendedIncidentAction,
)
from packages.incidents.investigator import (
    InvestigatorOutputError,
    LangGraphIncidentInvestigator,
)
from packages.incidents.timeline import IncidentTimelineBuilder

NOW = datetime(2026, 9, 11, 4, 0, tzinfo=UTC)


class FakeSummaryModel:
    name = "fake/incident-summary-v1"

    def __init__(self, draft: InvestigatorDraft) -> None:
        self.draft = draft
        self.requests: list[InvestigatorRequest] = []

    async def summarize(self, request: InvestigatorRequest) -> InvestigatorDraft:
        self.requests.append(request)
        return self.draft


def _context() -> tuple[UUID, UUID, InvestigatorRequest]:
    incident_id = uuid4()
    trigger = IncidentTrigger(
        id=uuid4(),
        incident_id=incident_id,
        trigger_type=IncidentTriggerType.QUALITY_REGRESSION,
        severity=IncidentSeverity.CRITICAL,
        signal_name="shadow.quality_confidence_low",
        observed_value=-0.05,
        threshold=-0.02,
        operator="<",
        source_ref="delivery://comparison/shopping-agent",
        summary="Candidate quality regressed below its minimum confidence bound",
        idempotency_key="investigator-quality-trigger",
        fingerprint="a" * 64,
        occurred_at=NOW,
        recorded_at=NOW,
    )
    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [trigger],
        [],
        generated_at=NOW,
    )
    finding = InvestigationClaim(
        kind=FindingKind.CHANGE_CORRELATION,
        statement="The candidate change preceded the quality regression",
        confidence=0.7,
        citations=[
            EvidenceCitation(
                evidence_id=trigger.id,
                source_ref=trigger.source_ref,
                content_hash=trigger.fingerprint,
            )
        ],
    )
    deterministic = DeterministicInvestigation(
        incident_id=incident_id,
        generated_at=NOW,
        probable_cause=finding,
        findings=[finding],
        counter_evidence=[],
        missing_evidence=[],
    )
    return (
        incident_id,
        trigger.id,
        InvestigatorRequest(
            incident_id=incident_id,
            deterministic=deterministic,
            timeline=timeline,
        ),
    )


def _claim(
    evidence_id: UUID, statement: str = "The supplied evidence supports this claim"
) -> DraftNarrativeClaim:
    return DraftNarrativeClaim(
        statement=statement,
        uncertainty="medium",
        citation_ids=[evidence_id],
    )


def _draft(evidence_id: UUID) -> InvestigatorDraft:
    return InvestigatorDraft(
        probable_cause=_claim(evidence_id, "The candidate change likely caused the regression"),
        observations=[_claim(evidence_id, "Quality declined after the candidate change")],
        counter_evidence=[],
        blast_radius=_claim(evidence_id, "The evidence covers candidate traffic only"),
        recommended_action=RecommendedIncidentAction.REQUEST_ROLLBACK,
        recommendation_rationale=_claim(
            evidence_id, "Requesting rollback is consistent with the cited regression"
        ),
    )


@pytest.mark.unit
def test_langgraph_investigator_resolves_only_supplied_citations() -> None:
    incident_id, evidence_id, request = _context()
    model = FakeSummaryModel(_draft(evidence_id))

    report = asyncio.run(
        LangGraphIncidentInvestigator(model).investigate(request, generated_at=NOW)
    )

    assert report.incident_id == incident_id
    assert report.generated_by == model.name
    assert report.probable_cause is not None
    assert report.probable_cause.citations[0].evidence_id == evidence_id
    assert report.recommended_action is RecommendedIncidentAction.REQUEST_ROLLBACK
    assert model.requests == [request]


@pytest.mark.unit
def test_investigator_rejects_unknown_or_invented_citations() -> None:
    _, evidence_id, request = _context()
    draft = _draft(evidence_id).model_copy(
        update={"probable_cause": _claim(uuid4(), "An unsupported cause was invented")}
    )

    with pytest.raises(InvestigatorOutputError, match="was not supplied"):
        asyncio.run(
            LangGraphIncidentInvestigator(FakeSummaryModel(draft)).investigate(
                request, generated_at=NOW
            )
        )


@pytest.mark.unit
def test_investigator_rejects_direct_infrastructure_actuation_text() -> None:
    _, evidence_id, request = _context()
    draft = _draft(evidence_id).model_copy(
        update={
            "recommendation_rationale": _claim(
                evidence_id, "Run kubectl delete deployment shopping-agent immediately"
            )
        }
    )

    with pytest.raises(InvestigatorOutputError, match="direct actuation path"):
        asyncio.run(
            LangGraphIncidentInvestigator(FakeSummaryModel(draft)).investigate(
                request, generated_at=NOW
            )
        )


@pytest.mark.unit
def test_investigator_cannot_add_a_cause_when_heuristics_found_none() -> None:
    _, evidence_id, request = _context()
    empty = request.model_copy(
        update={"deterministic": request.deterministic.model_copy(update={"probable_cause": None})}
    )

    with pytest.raises(InvestigatorOutputError, match="not supported"):
        asyncio.run(
            LangGraphIncidentInvestigator(FakeSummaryModel(_draft(evidence_id))).investigate(
                empty, generated_at=NOW
            )
        )


@pytest.mark.unit
def test_investigator_limits_and_incident_identity_are_validated() -> None:
    _, evidence_id, request = _context()
    with pytest.raises(ValueError, match="bounded steps"):
        LangGraphIncidentInvestigator(FakeSummaryModel(_draft(evidence_id)), max_steps=1)
    with pytest.raises(ValueError, match="different incident"):
        asyncio.run(
            LangGraphIncidentInvestigator(FakeSummaryModel(_draft(evidence_id))).investigate(
                request.model_copy(update={"incident_id": uuid4()}),
                generated_at=NOW,
            )
        )
