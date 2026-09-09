"""Release provenance and guarded state-machine tests."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.release import ReleaseProvenance, ReleaseState
from packages.release.lifecycle import can_transition, gate_decision, transition_reason

SHA = "a" * 40
HASH = "b" * 64
DIGEST = f"sha256:{'c' * 64}"
IMAGE = f"ghcr.io/muhmdk/agenthub/api@{DIGEST}"


@pytest.mark.unit
def test_provenance_hash_is_stable_and_content_addressed() -> None:
    values = {
        "schema_version": "agenthub.dev/release-provenance/v1",
        "source_repository": "https://github.com/Muhmdk/AgentHub",
        "source_sha": SHA,
        "image_reference": IMAGE,
        "image_digest": DIGEST,
        "manifest_hash": HASH,
        "sbom_digest": DIGEST,
        "build_provenance_digest": DIGEST,
        "evaluation_run_id": UUID("6f71dc7e-e32d-4a3c-9df5-c506c3414702"),
        "evaluation_artifact_hash": HASH,
        "policy_decision_id": "default-policy",
        "policy_decision_version": "1.0.0",
    }

    first = ReleaseProvenance.model_validate(values)
    second = ReleaseProvenance.model_validate(dict(reversed(list(values.items()))))

    assert first.provenance_hash == second.provenance_hash
    assert len(first.provenance_hash) == 64


@pytest.mark.unit
def test_provenance_rejects_mutable_image_reference() -> None:
    with pytest.raises(ValidationError, match="image_reference"):
        ReleaseProvenance(
            schema_version="agenthub.dev/release-provenance/v1",
            source_repository="https://github.com/Muhmdk/AgentHub",
            source_sha=SHA,
            image_reference="ghcr.io/muhmdk/agenthub/api:latest",
            image_digest=DIGEST,
            manifest_hash=HASH,
            sbom_digest=DIGEST,
            build_provenance_digest=DIGEST,
            evaluation_run_id=UUID("6f71dc7e-e32d-4a3c-9df5-c506c3414702"),
            evaluation_artifact_hash=HASH,
            policy_decision_id="default-policy",
            policy_decision_version="1.0.0",
        )


@pytest.mark.unit
def test_promotion_requires_every_gate_and_preserves_order() -> None:
    passed = gate_decision(
        evaluation_passed=True,
        dependency_scan_passed=True,
        image_scan_passed=True,
        policy_passed=True,
    )

    assert can_transition(ReleaseState.EVALUATED, ReleaseState.APPROVED, passed)
    assert can_transition(ReleaseState.APPROVED, ReleaseState.STAGED, passed)
    assert can_transition(ReleaseState.STAGED, ReleaseState.PRODUCTION, passed)
    assert not can_transition(ReleaseState.EVALUATED, ReleaseState.PRODUCTION, passed)
    assert not can_transition(ReleaseState.PRODUCTION, ReleaseState.STAGED, passed)


@pytest.mark.unit
def test_failed_evaluation_blocks_promotion_with_machine_reason() -> None:
    blocked = gate_decision(
        evaluation_passed=False,
        dependency_scan_passed=True,
        image_scan_passed=True,
        policy_passed=True,
    )

    assert blocked.reasons == ["evaluation_gate_failed"]
    assert not can_transition(ReleaseState.EVALUATED, ReleaseState.APPROVED, blocked)
    assert (
        transition_reason(ReleaseState.EVALUATED, ReleaseState.APPROVED, blocked)
        == "Promotion is blocked: evaluation_gate_failed"
    )


@pytest.mark.unit
def test_failed_partial_promotion_can_retry_only_after_all_gates_pass() -> None:
    blocked = gate_decision(
        evaluation_passed=True,
        dependency_scan_passed=True,
        image_scan_passed=False,
        policy_passed=True,
    )
    passed = blocked.model_copy(update={"passed": True, "security_passed": True, "reasons": []})

    assert can_transition(ReleaseState.EVALUATED, ReleaseState.FAILED, blocked)
    assert not can_transition(ReleaseState.FAILED, ReleaseState.APPROVED, blocked)
    assert can_transition(ReleaseState.FAILED, ReleaseState.APPROVED, passed)
