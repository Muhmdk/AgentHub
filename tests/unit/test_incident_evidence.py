"""Evidence adapter coverage for telemetry, releases, and manifest changes."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from packages.contracts.manifest import AgentManifest
from packages.contracts.registry import AgentVersionView, LifecycleState
from packages.contracts.release import (
    PolicyAttestation,
    ReleaseEventView,
    ReleaseGateDecision,
    ReleaseProvenance,
    ReleaseState,
    ReleaseView,
    SecurityAttestation,
)
from packages.incidents.evidence import (
    ConfigEvidenceAdapter,
    ReleaseEvidenceAdapter,
    TelemetryEvidenceAdapter,
)
from packages.observability.conventions import Attribute
from packages.observability.telemetry import Observation

ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)


@pytest.mark.unit
def test_telemetry_adapter_allowlists_dimensions_and_has_stable_identity() -> None:
    observation = Observation(
        occurred_at=NOW.timestamp(),
        signal="agent.duration_ms",
        value=250,
        attributes={
            Attribute.AGENT_NAME.value: "shopping-agent",
            Attribute.AGENT_VERSION.value: "2.0.0",
            "prompt.content": "customer@example.com bearer secret-token-value",
        },
    )

    first = TelemetryEvidenceAdapter.collect(
        [observation],
        idempotency_prefix="incident-telemetry",
        source_ref="telemetry://shopping-agent/metrics",
    )
    replay = TelemetryEvidenceAdapter.collect(
        [observation],
        idempotency_prefix="incident-telemetry",
        source_ref="telemetry://shopping-agent/metrics",
    )

    assert first == replay
    assert first[0].attributes["dimensions"] == {
        "agent.name": "shopping-agent",
        "agent.version": "2.0.0",
    }
    assert "prompt.content" not in str(first[0].attributes)


def _release() -> tuple[ReleaseView, ReleaseEventView]:
    release_id = uuid4()
    provenance = ReleaseProvenance(
        schema_version="agenthub.dev/release-provenance/v1",
        source_repository="https://example.invalid/agenthub",
        source_sha="a" * 40,
        image_reference=f"registry.example/agent@sha256:{'b' * 64}",
        image_digest=f"sha256:{'b' * 64}",
        manifest_hash="c" * 64,
        evaluation_run_id=uuid4(),
        evaluation_artifact_hash="d" * 64,
        sbom_digest=f"sha256:{'e' * 64}",
        build_provenance_digest=f"sha256:{'f' * 64}",
        policy_decision_id="release-policy",
        policy_decision_version="1.0.0",
    )
    release = ReleaseView(
        id=release_id,
        agent_version_id=uuid4(),
        agent_name="shopping-agent",
        agent_version="2.0.0",
        state=ReleaseState.PRODUCTION,
        state_revision=4,
        idempotency_key="release-test-evidence",
        provenance=provenance,
        provenance_hash=provenance.provenance_hash,
        security=SecurityAttestation(
            dependency_scan_passed=True,
            image_scan_passed=True,
            maximum_severity="none",
            scanner="test",
            scanner_version="1",
        ),
        policy=PolicyAttestation(
            decision_id="release-policy",
            decision_version="1.0.0",
            passed=True,
            reasons=[],
        ),
        gate=ReleaseGateDecision(
            passed=True,
            evaluation_passed=True,
            security_passed=True,
            policy_passed=True,
            reasons=[],
        ),
        created_by="release-test",
        created_at=NOW,
        updated_at=NOW,
    )
    event = ReleaseEventView(
        id=uuid4(),
        release_id=release_id,
        event_type="release_transition",
        actor="release-test",
        occurred_at=NOW,
        previous_state=ReleaseState.STAGED,
        new_state=ReleaseState.PRODUCTION,
        idempotency_key="release-test-production",
        reason="Promote known good release",
        provenance_hash=release.provenance_hash,
    )
    return release, event


@pytest.mark.unit
def test_release_adapter_preserves_immutable_deployment_lineage() -> None:
    release, event = _release()

    evidence = ReleaseEvidenceAdapter.collect(release, [event])

    assert len(evidence) == 1
    assert evidence[0].attributes["new_state"] == "production"
    assert evidence[0].attributes["provenance_hash"] == release.provenance_hash
    assert str(release.id) in evidence[0].source_ref


@pytest.mark.unit
def test_config_adapter_records_field_level_change_without_prompt_content() -> None:
    manifest = AgentManifest.model_validate_json(
        (ROOT / "data/manifests/shopping-agent-v1.json").read_text()
    )
    assert manifest.spec.retrieval is not None
    updated_manifest = manifest.model_copy(
        update={
            "metadata": manifest.metadata.model_copy(update={"version": "1.1.0"}),
            "spec": manifest.spec.model_copy(
                update={"retrieval": manifest.spec.retrieval.model_copy(update={"top_k": 10})}
            ),
        }
    )
    previous = AgentVersionView(
        id=uuid4(),
        agent_id=uuid4(),
        version="1.0.0",
        manifest_hash=manifest.manifest_hash,
        manifest=manifest,
        lifecycle_state=LifecycleState.PRODUCTION,
        state_revision=4,
        created_at=NOW,
    )
    current = AgentVersionView(
        id=uuid4(),
        agent_id=previous.agent_id,
        version="1.1.0",
        manifest_hash=updated_manifest.manifest_hash,
        manifest=updated_manifest,
        lifecycle_state=LifecycleState.CANARY,
        state_revision=3,
        created_at=NOW,
    )

    evidence = ConfigEvidenceAdapter.compare(previous, current)
    changes = evidence.attributes["changes"]

    assert isinstance(changes, dict)
    assert changes["spec.retrieval.top_k"] == {"before": 5, "after": 10}
    assert "content" not in str(evidence.attributes).lower()
