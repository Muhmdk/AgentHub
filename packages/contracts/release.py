"""Immutable candidate provenance and guarded release lifecycle contracts."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.manifest import ImageReference, SemanticVersion, Slug, SourceSha

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class ReleaseState(StrEnum):
    EVALUATED = "evaluated"
    APPROVED = "approved"
    STAGED = "staged"
    PRODUCTION = "production"
    REJECTED = "rejected"
    FAILED = "failed"


class SecurityAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dependency_scan_passed: bool
    image_scan_passed: bool
    maximum_severity: Literal["none", "low", "medium", "high", "critical"]
    scanner: str = Field(min_length=2, max_length=100)
    scanner_version: str = Field(min_length=1, max_length=64)


class PolicyAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: Slug
    decision_version: SemanticVersion
    passed: bool
    reasons: list[str] = Field(default_factory=list, max_length=50)


class ReleaseGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    evaluation_passed: bool
    security_passed: bool
    policy_passed: bool
    reasons: list[str]


class CreateCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    agent_name: Slug
    agent_version: SemanticVersion
    evaluation_run_id: UUID
    sbom_digest: Digest
    build_provenance_digest: Digest
    security: SecurityAttestation
    policy: PolicyAttestation
    actor: str = Field(min_length=2, max_length=200)


class ReleaseProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/release-provenance/v1"]
    source_repository: str = Field(min_length=1, max_length=500)
    source_sha: SourceSha
    image_reference: ImageReference
    image_digest: Digest
    manifest_hash: Sha256
    sbom_digest: Digest
    build_provenance_digest: Digest
    evaluation_run_id: UUID
    evaluation_artifact_hash: Sha256
    policy_decision_id: Slug
    policy_decision_version: SemanticVersion

    @property
    def provenance_hash(self) -> Sha256:
        payload = self.model_dump(mode="json", exclude={"provenance_hash"})
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class ReleaseView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    agent_version_id: UUID
    agent_name: Slug
    agent_version: SemanticVersion
    state: ReleaseState
    state_revision: int = Field(ge=1)
    idempotency_key: IdempotencyKey
    provenance: ReleaseProvenance
    provenance_hash: Sha256
    security: SecurityAttestation
    policy: PolicyAttestation
    gate: ReleaseGateDecision
    created_by: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def verify_provenance_hash(self) -> ReleaseView:
        if self.provenance_hash != self.provenance.provenance_hash:
            raise ValueError("Release provenance hash does not match its content")
        return self


class CandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    release: ReleaseView


class PromoteReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_state: Literal[
        ReleaseState.APPROVED,
        ReleaseState.STAGED,
        ReleaseState.PRODUCTION,
        ReleaseState.REJECTED,
        ReleaseState.FAILED,
    ]
    actor: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=3, max_length=500)
    expected_revision: int = Field(ge=1)
    idempotency_key: IdempotencyKey


class ReleaseEventView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    release_id: UUID
    event_type: str
    actor: str
    occurred_at: datetime
    previous_state: ReleaseState | None
    new_state: ReleaseState
    idempotency_key: IdempotencyKey
    reason: str
    provenance_hash: Sha256


class ReleaseNotes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    release_id: UUID
    title: str
    summary: str
    source_sha: SourceSha
    image_reference: ImageReference
    evaluation_run_id: UUID
    policy_decision_id: Slug
    state: ReleaseState
