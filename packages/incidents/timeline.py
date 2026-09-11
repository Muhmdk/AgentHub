"""Deterministic normalization of incident triggers and evidence onto one timeline."""

from datetime import datetime, timedelta
from uuid import UUID

from packages.contracts.incident import (
    EvidenceKind,
    IncidentEvidence,
    IncidentTimeline,
    IncidentTrigger,
    TimelineEntry,
)


class IncidentTimelineBuilder:
    """Order evidence without hiding clock skew, missing sources, or contradictions."""

    def __init__(self, *, future_skew_tolerance_seconds: float = 60) -> None:
        if future_skew_tolerance_seconds < 0:
            raise ValueError("Future clock-skew tolerance cannot be negative")
        self._future_skew_tolerance = timedelta(seconds=future_skew_tolerance_seconds)

    def build(
        self,
        incident_id: UUID,
        triggers: list[IncidentTrigger],
        evidence: list[IncidentEvidence],
        *,
        expected_sources: set[EvidenceKind] | None = None,
        generated_at: datetime,
    ) -> IncidentTimeline:
        self._require_aware(generated_at)
        entries = [self._trigger_entry(item) for item in triggers]
        entries.extend(self._evidence_entry(item) for item in evidence)
        entries.sort(
            key=lambda entry: (
                entry.normalized_at,
                entry.category,
                entry.kind,
                str(entry.entry_id),
            )
        )
        observed_sources = {item.kind for item in evidence}
        missing = sorted((expected_sources or set()) - observed_sources, key=str)
        warnings = self._contradiction_warnings(evidence)
        skewed = [entry for entry in entries if entry.clock_skew_seconds > 0]
        if skewed:
            warnings.append(f"Clock skew detected in {len(skewed)} timeline entries")
        if missing:
            warnings.append(
                "Missing evidence sources: " + ", ".join(source.value for source in missing)
            )
        return IncidentTimeline(
            incident_id=incident_id,
            generated_at=generated_at,
            entries=entries,
            missing_sources=missing,
            warnings=warnings,
            clock_skew_detected=bool(skewed),
        )

    def _trigger_entry(self, trigger: IncidentTrigger) -> TimelineEntry:
        normalized, skew = self._normalize_time(trigger.occurred_at, trigger.recorded_at)
        return TimelineEntry(
            entry_id=trigger.id,
            category="trigger",
            kind=trigger.trigger_type.value,
            source_ref=trigger.source_ref,
            summary=trigger.summary,
            occurred_at=trigger.occurred_at,
            normalized_at=normalized,
            recorded_at=trigger.recorded_at,
            content_hash=trigger.fingerprint,
            subject_id=trigger.signal_name,
            clock_skew_seconds=skew,
        )

    def _evidence_entry(self, evidence: IncidentEvidence) -> TimelineEntry:
        normalized, skew = self._normalize_time(evidence.occurred_at, evidence.collected_at)
        return TimelineEntry(
            entry_id=evidence.id,
            category="evidence",
            kind=evidence.kind.value,
            source_ref=evidence.source_ref,
            summary=evidence.summary,
            occurred_at=evidence.occurred_at,
            normalized_at=normalized,
            recorded_at=evidence.collected_at,
            content_hash=evidence.content_hash,
            subject_id=evidence.subject_id,
            clock_skew_seconds=skew,
        )

    def _normalize_time(
        self, occurred_at: datetime, recorded_at: datetime
    ) -> tuple[datetime, float]:
        self._require_aware(occurred_at)
        self._require_aware(recorded_at)
        skew = (occurred_at - recorded_at).total_seconds()
        if occurred_at > recorded_at + self._future_skew_tolerance:
            return recorded_at, skew
        return occurred_at, 0

    @staticmethod
    def _contradiction_warnings(evidence: list[IncidentEvidence]) -> list[str]:
        grouped: dict[tuple[EvidenceKind, str, datetime], set[str]] = {}
        for item in evidence:
            if item.subject_id is None:
                continue
            key = (item.kind, item.subject_id, item.occurred_at)
            grouped.setdefault(key, set()).add(item.content_hash)
        return [
            f"Contradictory {kind.value} evidence for {subject} at {occurred_at.isoformat()}"
            for (kind, subject, occurred_at), hashes in sorted(
                grouped.items(), key=lambda item: (str(item[0][0]), item[0][1], item[0][2])
            )
            if len(hashes) > 1
        ]

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timeline timestamps must be timezone-aware")
