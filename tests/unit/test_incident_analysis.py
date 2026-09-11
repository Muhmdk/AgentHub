"""Grounded deterministic incident-correlation analysis coverage."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from packages.contracts.incident import (
    EvidenceKind,
    FindingKind,
    IncidentEvidence,
    IncidentSeverity,
    IncidentTrigger,
    IncidentTriggerType,
)
from packages.contracts.runtime import JsonValue
from packages.incidents.analysis import DeterministicIncidentAnalyzer
from packages.incidents.timeline import IncidentTimelineBuilder

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=UTC)


def _trigger(incident_id: UUID) -> IncidentTrigger:
    return IncidentTrigger(
        id=uuid4(),
        incident_id=incident_id,
        trigger_type=IncidentTriggerType.SLO_BURN,
        severity=IncidentSeverity.CRITICAL,
        signal_name="slo.latency.burn_rate",
        observed_value=20,
        threshold=14.4,
        operator=">=",
        source_ref="telemetry://shopping-agent/slo/latency",
        summary="Shopping Agent latency exhausted its error budget",
        idempotency_key="analysis-latency-trigger",
        fingerprint="a" * 64,
        occurred_at=NOW,
        recorded_at=NOW,
    )


def _evidence(
    incident_id: UUID,
    *,
    kind: EvidenceKind,
    subject: str,
    attributes: dict[str, JsonValue],
    occurred_at: datetime = NOW - timedelta(minutes=1),
    digest: str = "b",
) -> IncidentEvidence:
    return IncidentEvidence(
        id=uuid4(),
        incident_id=incident_id,
        kind=kind,
        source_ref=f"evidence://{kind.value}/{subject}",
        summary=f"Collected evidence for {subject}",
        occurred_at=occurred_at,
        subject_id=subject,
        attributes=attributes,
        content_hash=digest * 64,
        idempotency_key=f"analysis-{kind.value}-{digest * 8}",
        collected_by="incident-analyzer",
        collected_at=NOW,
    )


@pytest.mark.unit
def test_analysis_correlates_top_k_change_and_retrieval_latency_with_citations() -> None:
    incident_id = uuid4()
    trigger = _trigger(incident_id)
    config = _evidence(
        incident_id,
        kind=EvidenceKind.CONFIG_DIFF,
        subject="shopping-agent-config",
        attributes={"changes": {"spec.retrieval.top_k": {"before": 5, "after": 50}}},
        occurred_at=NOW - timedelta(minutes=10),
        digest="b",
    )
    retrieval = _evidence(
        incident_id,
        kind=EvidenceKind.METRIC,
        subject="retrieval.duration_ms",
        attributes={"baseline": 100, "current": 500, "delta": 400, "change_ratio": 4.0},
        digest="c",
    )
    errors = _evidence(
        incident_id,
        kind=EvidenceKind.METRIC,
        subject="agent.error_rate",
        attributes={"baseline": 0.01, "current": 0.02, "change_ratio": 1.0},
        digest="d",
    )
    model = _evidence(
        incident_id,
        kind=EvidenceKind.METRIC,
        subject="model.duration_ms",
        attributes={"baseline": 200, "current": 202, "delta": 2, "change_ratio": 0.01},
        digest="e",
    )
    evidence = [model, retrieval, config, errors]
    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [trigger],
        evidence,
        generated_at=NOW,
    )

    analysis = DeterministicIncidentAnalyzer().analyze(
        incident_id,
        timeline,
        evidence,
        generated_at=NOW,
    )

    assert {finding.kind for finding in analysis.findings} == {
        FindingKind.CHANGE_CORRELATION,
        FindingKind.SPAN_CONTRIBUTION,
        FindingKind.METRIC_CO_MOVEMENT,
        FindingKind.KNOWN_SIGNATURE,
    }
    assert analysis.probable_cause is not None
    assert analysis.probable_cause.kind is FindingKind.KNOWN_SIGNATURE
    assert "retrieval fan-out" in analysis.probable_cause.statement
    assert analysis.counter_evidence[0].kind is FindingKind.COUNTER_EVIDENCE
    assert "Model latency remained" in analysis.counter_evidence[0].statement
    stored_ids = {item.id for item in evidence} | {trigger.id}
    for claim in [*analysis.findings, *analysis.counter_evidence]:
        assert claim.citations
        assert {citation.evidence_id for citation in claim.citations} <= stored_ids
        assert all(citation.source_ref and citation.content_hash for citation in claim.citations)


@pytest.mark.unit
def test_analysis_states_missing_evidence_and_does_not_invent_a_cause() -> None:
    incident_id = uuid4()
    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [_trigger(incident_id)],
        [],
        expected_sources={EvidenceKind.CONFIG_DIFF, EvidenceKind.TRACE},
        generated_at=NOW,
    )

    analysis = DeterministicIncidentAnalyzer().analyze(
        incident_id,
        timeline,
        [],
        generated_at=NOW,
    )

    assert analysis.probable_cause is None
    assert analysis.findings == []
    assert analysis.missing_evidence == [EvidenceKind.CONFIG_DIFF, EvidenceKind.TRACE]


@pytest.mark.unit
def test_change_after_trigger_is_not_reported_as_causal_precedence() -> None:
    incident_id = uuid4()
    trigger = _trigger(incident_id)
    later = _evidence(
        incident_id,
        kind=EvidenceKind.DEPLOYMENT,
        subject="release-later",
        attributes={"new_state": "production"},
        occurred_at=NOW + timedelta(minutes=1),
    )
    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [trigger],
        [later],
        generated_at=NOW + timedelta(minutes=2),
    )

    analysis = DeterministicIncidentAnalyzer().analyze(
        incident_id,
        timeline,
        [later],
        generated_at=NOW + timedelta(minutes=2),
    )

    assert all(item.kind is not FindingKind.CHANGE_CORRELATION for item in analysis.findings)


@pytest.mark.unit
def test_analysis_rejects_cross_incident_timeline_and_invalid_window() -> None:
    incident_id = uuid4()
    timeline = IncidentTimelineBuilder().build(incident_id, [], [], generated_at=NOW)
    with pytest.raises(ValueError, match="positive"):
        DeterministicIncidentAnalyzer(change_window_seconds=0)
    with pytest.raises(ValueError, match="does not belong"):
        DeterministicIncidentAnalyzer().analyze(uuid4(), timeline, [], generated_at=NOW)
