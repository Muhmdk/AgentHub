"""Candidate lineage assembly and release-note generation."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from packages.contracts.release import (
    CandidateResult,
    CreateCandidateRequest,
    PromoteReleaseRequest,
    ReleaseNotes,
    ReleaseProvenance,
    ReleaseState,
    ReleaseView,
)
from packages.evaluation.repository import EvaluationStore
from packages.registry.repository import RegistryStore
from packages.release.lifecycle import gate_decision
from packages.release.repository import ReleaseConflictError, ReleaseStore


class ReleaseService:
    def __init__(
        self,
        registry: RegistryStore,
        evaluations: EvaluationStore,
        releases: ReleaseStore,
    ) -> None:
        self._registry = registry
        self._evaluations = evaluations
        self._releases = releases

    def create_candidate(self, request: CreateCandidateRequest) -> CandidateResult:
        version = self._registry.get_version(request.agent_name, request.agent_version)
        evaluation = self._evaluations.get(request.evaluation_run_id)
        if (
            evaluation.agent_version_id != version.id
            or evaluation.agent_name != request.agent_name
            or evaluation.agent_version != request.agent_version
            or evaluation.manifest_hash != version.manifest_hash
        ):
            raise ReleaseConflictError(
                "Evaluation artifact does not match the immutable candidate version"
            )
        image_reference = version.manifest.spec.runtime.image
        image_digest = image_reference.rsplit("@", maxsplit=1)[1]
        provenance = ReleaseProvenance(
            schema_version="agenthub.dev/release-provenance/v1",
            source_repository=version.manifest.spec.source.repository,
            source_sha=version.manifest.spec.source.commit_sha,
            image_reference=image_reference,
            image_digest=image_digest,
            manifest_hash=version.manifest_hash,
            sbom_digest=request.sbom_digest,
            build_provenance_digest=request.build_provenance_digest,
            evaluation_run_id=evaluation.run_id,
            evaluation_artifact_hash=evaluation.artifact_hash,
            policy_decision_id=request.policy.decision_id,
            policy_decision_version=request.policy.decision_version,
        )
        gate = gate_decision(
            evaluation_passed=evaluation.gate.passed,
            dependency_scan_passed=request.security.dependency_scan_passed,
            image_scan_passed=request.security.image_scan_passed,
            policy_passed=request.policy.passed,
        )
        now = datetime.now(UTC)
        release = ReleaseView(
            id=uuid4(),
            agent_version_id=version.id,
            agent_name=request.agent_name,
            agent_version=request.agent_version,
            state=ReleaseState.EVALUATED,
            state_revision=1,
            idempotency_key=request.idempotency_key,
            provenance=provenance,
            provenance_hash=provenance.provenance_hash,
            security=request.security,
            policy=request.policy,
            gate=gate,
            created_by=request.actor,
            created_at=now,
            updated_at=now,
        )
        fingerprint = self._fingerprint(request, release)
        return self._releases.create(release, fingerprint)

    def promote(self, release_id: UUID, change: PromoteReleaseRequest) -> ReleaseView:
        return self._releases.transition(release_id, change)

    def notes(self, release_id: UUID) -> ReleaseNotes:
        release = self._releases.get(release_id)
        return ReleaseNotes(
            release_id=release.id,
            title=f"{release.agent_name} {release.agent_version}",
            summary=(
                f"Release {release.state.value} from source "
                f"{release.provenance.source_sha[:12]} with immutable image "
                "and evaluation evidence."
            ),
            source_sha=release.provenance.source_sha,
            image_reference=release.provenance.image_reference,
            evaluation_run_id=release.provenance.evaluation_run_id,
            policy_decision_id=release.provenance.policy_decision_id,
            state=release.state,
        )

    @staticmethod
    def _fingerprint(request: CreateCandidateRequest, release: ReleaseView) -> str:
        payload = {
            "request": request.model_dump(mode="json"),
            "agent_version_id": str(release.agent_version_id),
            "provenance_hash": release.provenance_hash,
        }
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
