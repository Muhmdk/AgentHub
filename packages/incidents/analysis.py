"""Deterministic incident correlation heuristics over stored evidence only."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from packages.contracts.incident import (
    DeterministicInvestigation,
    EvidenceCitation,
    EvidenceKind,
    FindingKind,
    IncidentEvidence,
    IncidentTimeline,
    InvestigationClaim,
    TimelineEntry,
)


class DeterministicIncidentAnalyzer:
    """Run bounded, explainable heuristics before any generated summary."""

    def __init__(self, *, change_window_seconds: float = 1800) -> None:
        if change_window_seconds <= 0:
            raise ValueError("Change-correlation window must be positive")
        self._change_window = timedelta(seconds=change_window_seconds)

    def analyze(
        self,
        incident_id: UUID,
        timeline: IncidentTimeline,
        evidence: list[IncidentEvidence],
        *,
        generated_at: datetime,
    ) -> DeterministicInvestigation:
        if timeline.incident_id != incident_id:
            raise ValueError("Timeline does not belong to the investigated incident")
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("Investigation timestamps must be timezone-aware")
        findings: list[InvestigationClaim] = []
        counter_evidence: list[InvestigationClaim] = []
        change = self._change_correlation(timeline, evidence)
        if change is not None:
            findings.append(change)
        contribution = self._span_contribution(evidence)
        if contribution is not None:
            findings.append(contribution)
        movement = self._metric_co_movement(evidence)
        if movement is not None:
            findings.append(movement)
        signature, counter = self._known_signature(evidence)
        if signature is not None:
            findings.append(signature)
        if counter is not None:
            counter_evidence.append(counter)
        probable = signature or change or contribution or movement
        return DeterministicInvestigation(
            incident_id=incident_id,
            generated_at=generated_at,
            probable_cause=probable,
            findings=findings,
            counter_evidence=counter_evidence,
            missing_evidence=timeline.missing_sources,
        )

    def _change_correlation(
        self, timeline: IncidentTimeline, evidence: list[IncidentEvidence]
    ) -> InvestigationClaim | None:
        triggers = [entry for entry in timeline.entries if entry.category == "trigger"]
        if not triggers:
            return None
        trigger = min(triggers, key=lambda entry: entry.normalized_at)
        changes = [
            item
            for item in evidence
            if item.kind in {EvidenceKind.CONFIG_DIFF, EvidenceKind.DEPLOYMENT}
            and trigger.normalized_at - self._change_window
            <= item.occurred_at
            <= trigger.normalized_at
        ]
        if not changes:
            return None
        change = max(changes, key=lambda item: item.occurred_at)
        seconds = (trigger.normalized_at - change.occurred_at).total_seconds()
        return InvestigationClaim(
            kind=FindingKind.CHANGE_CORRELATION,
            statement=(
                f"{change.kind.value} evidence preceded the incident trigger by "
                f"{seconds:.0f} seconds"
            ),
            confidence=0.7,
            citations=[self._citation(change), self._timeline_citation(trigger)],
        )

    @staticmethod
    def _span_contribution(evidence: list[IncidentEvidence]) -> InvestigationClaim | None:
        contributions: list[tuple[float, IncidentEvidence]] = []
        for item in evidence:
            if item.kind is not EvidenceKind.METRIC or not item.subject_id:
                continue
            if "duration" not in item.subject_id and "latency" not in item.subject_id:
                continue
            delta = _delta(item.attributes)
            if delta is not None and delta > 0:
                contributions.append((delta, item))
        if not contributions:
            return None
        delta, item = max(contributions, key=lambda value: value[0])
        return InvestigationClaim(
            kind=FindingKind.SPAN_CONTRIBUTION,
            statement=f"{item.subject_id} contributed the largest measured increase ({delta:g})",
            confidence=0.8,
            citations=[DeterministicIncidentAnalyzer._citation(item)],
        )

    @staticmethod
    def _metric_co_movement(evidence: list[IncidentEvidence]) -> InvestigationClaim | None:
        moving: list[tuple[float, IncidentEvidence]] = []
        for item in evidence:
            if item.kind is not EvidenceKind.METRIC:
                continue
            ratio = _number(item.attributes.get("change_ratio"))
            if ratio is not None and abs(ratio) >= 0.05:
                moving.append((ratio, item))
        positive = [item for ratio, item in moving if ratio > 0]
        negative = [item for ratio, item in moving if ratio < 0]
        aligned = positive if len(positive) >= len(negative) else negative
        if len(aligned) < 2:
            return None
        direction = "increased" if aligned is positive else "decreased"
        subjects = ", ".join(sorted(item.subject_id or item.summary for item in aligned))
        return InvestigationClaim(
            kind=FindingKind.METRIC_CO_MOVEMENT,
            statement=f"Related metrics {direction} together: {subjects}",
            confidence=0.65,
            citations=[DeterministicIncidentAnalyzer._citation(item) for item in aligned[:10]],
        )

    @staticmethod
    def _known_signature(
        evidence: list[IncidentEvidence],
    ) -> tuple[InvestigationClaim | None, InvestigationClaim | None]:
        config = next(
            (
                item
                for item in evidence
                if item.kind is EvidenceKind.CONFIG_DIFF and _top_k_increased(item.attributes)
            ),
            None,
        )
        retrieval = next(
            (
                item
                for item in evidence
                if item.kind is EvidenceKind.METRIC
                and item.subject_id == "retrieval.duration_ms"
                and (_delta(item.attributes) or 0) > 0
            ),
            None,
        )
        model = next(
            (
                item
                for item in evidence
                if item.kind is EvidenceKind.METRIC and item.subject_id == "model.duration_ms"
            ),
            None,
        )
        signature = None
        if config is not None and retrieval is not None:
            signature = InvestigationClaim(
                kind=FindingKind.KNOWN_SIGNATURE,
                statement=(
                    "Increased retrieval top_k coincided with higher retrieval latency, "
                    "matching the retrieval fan-out signature"
                ),
                confidence=0.95,
                citations=[
                    DeterministicIncidentAnalyzer._citation(config),
                    DeterministicIncidentAnalyzer._citation(retrieval),
                ],
            )
        counter = None
        if model is not None:
            ratio = _number(model.attributes.get("change_ratio"))
            if ratio is not None and abs(ratio) < 0.05:
                counter = InvestigationClaim(
                    kind=FindingKind.COUNTER_EVIDENCE,
                    statement="Model latency remained within five percent of its baseline",
                    confidence=0.9,
                    citations=[DeterministicIncidentAnalyzer._citation(model)],
                )
        return signature, counter

    @staticmethod
    def _citation(item: IncidentEvidence) -> EvidenceCitation:
        return EvidenceCitation(
            evidence_id=item.id,
            source_ref=item.source_ref,
            content_hash=item.content_hash,
        )

    @staticmethod
    def _timeline_citation(item: TimelineEntry) -> EvidenceCitation:
        return EvidenceCitation(
            evidence_id=item.entry_id,
            source_ref=item.source_ref,
            content_hash=item.content_hash,
        )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _delta(attributes: dict[str, Any]) -> float | None:
    direct = _number(attributes.get("delta"))
    if direct is not None:
        return direct
    baseline = _number(attributes.get("baseline"))
    current = _number(attributes.get("current"))
    if baseline is None or current is None:
        return None
    return current - baseline


def _top_k_increased(attributes: dict[str, Any]) -> bool:
    changes = attributes.get("changes")
    if not isinstance(changes, dict):
        return False
    top_k = changes.get("spec.retrieval.top_k")
    if not isinstance(top_k, dict):
        return False
    before = _number(top_k.get("before"))
    after = _number(top_k.get("after"))
    return before is not None and after is not None and after > before
