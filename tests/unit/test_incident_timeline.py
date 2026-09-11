"""Incident timeline ordering and evidence-quality coverage."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from packages.contracts.incident import (
    EvidenceKind,
    IncidentEvidence,
    IncidentSeverity,
    IncidentTrigger,
    IncidentTriggerType,
)
from packages.incidents.timeline import IncidentTimelineBuilder

NOW = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)


def _trigger(*, occurred_at: datetime, recorded_at: datetime) -> IncidentTrigger:
    return IncidentTrigger(
        id=uuid4(),
        incident_id=uuid4(),
        trigger_type=IncidentTriggerType.ERROR_RATE,
        severity=IncidentSeverity.CRITICAL,
        signal_name="agent.error_rate",
        observed_value=0.08,
        threshold=0.01,
        operator=">",
        source_ref="telemetry://shopping-agent/error-rate",
        summary="Production error rate crossed its maximum",
        idempotency_key="timeline-error-trigger",
        fingerprint="a" * 64,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
    )


def _evidence(
    *,
    occurred_at: datetime,
    collected_at: datetime,
    kind: EvidenceKind = EvidenceKind.METRIC,
    subject_id: str = "agent.error_rate",
    content_hash: str = "b" * 64,
) -> IncidentEvidence:
    return IncidentEvidence(
        id=uuid4(),
        incident_id=uuid4(),
        kind=kind,
        source_ref=f"evidence://{kind.value}/{subject_id}",
        summary=f"Collected {kind.value} evidence",
        occurred_at=occurred_at,
        subject_id=subject_id,
        attributes={"value": 0.08},
        content_hash=content_hash,
        idempotency_key=f"timeline-{kind.value}-{content_hash[:8]}",
        collected_by="evidence-collector",
        collected_at=collected_at,
    )


@pytest.mark.unit
def test_timeline_orders_sources_and_preserves_links_and_hashes() -> None:
    incident_id = uuid4()
    trigger = _trigger(occurred_at=NOW - timedelta(minutes=1), recorded_at=NOW)
    earlier = _evidence(
        occurred_at=NOW - timedelta(minutes=5),
        collected_at=NOW,
        kind=EvidenceKind.DEPLOYMENT,
        subject_id="release-1",
    )

    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [trigger],
        [earlier],
        generated_at=NOW,
    )

    assert [entry.category for entry in timeline.entries] == ["evidence", "trigger"]
    assert [entry.content_hash for entry in timeline.entries] == ["b" * 64, "a" * 64]
    assert all(entry.source_ref for entry in timeline.entries)


@pytest.mark.unit
def test_future_clock_skew_is_clamped_and_reported() -> None:
    trigger = _trigger(occurred_at=NOW + timedelta(minutes=5), recorded_at=NOW)

    timeline = IncidentTimelineBuilder(future_skew_tolerance_seconds=30).build(
        trigger.incident_id,
        [trigger],
        [],
        generated_at=NOW,
    )

    assert timeline.clock_skew_detected is True
    assert timeline.entries[0].normalized_at == NOW
    assert timeline.entries[0].clock_skew_seconds == 300
    assert "Clock skew detected" in timeline.warnings[0]


@pytest.mark.unit
def test_missing_sources_are_explicit_and_deterministically_sorted() -> None:
    incident_id = uuid4()
    metric = _evidence(occurred_at=NOW, collected_at=NOW)

    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [],
        [metric],
        expected_sources={EvidenceKind.TRACE, EvidenceKind.DEPLOYMENT, EvidenceKind.METRIC},
        generated_at=NOW,
    )

    assert timeline.missing_sources == [EvidenceKind.DEPLOYMENT, EvidenceKind.TRACE]
    assert timeline.warnings == ["Missing evidence sources: deployment, trace"]


@pytest.mark.unit
def test_contradictory_same_source_time_is_retained_and_flagged() -> None:
    incident_id = uuid4()
    first = _evidence(occurred_at=NOW, collected_at=NOW, content_hash="b" * 64)
    second = _evidence(occurred_at=NOW, collected_at=NOW, content_hash="c" * 64)

    timeline = IncidentTimelineBuilder().build(
        incident_id,
        [],
        [second, first],
        generated_at=NOW,
    )

    assert len(timeline.entries) == 2
    assert timeline.warnings == [
        f"Contradictory metric evidence for agent.error_rate at {NOW.isoformat()}"
    ]


@pytest.mark.unit
def test_timeline_configuration_and_timestamps_are_bounded() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        IncidentTimelineBuilder(future_skew_tolerance_seconds=-1)
    with pytest.raises(ValueError, match="timezone-aware"):
        IncidentTimelineBuilder().build(uuid4(), [], [], generated_at=datetime(2026, 9, 11))
