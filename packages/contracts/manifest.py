"""Versioned, provider-neutral agent manifest contract."""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from packages.contracts.runtime import JsonValue

Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=63,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    ),
]
SemanticVersion = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
]
SourceSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
ImageReference = Annotated[
    str,
    StringConstraints(
        min_length=72,
        max_length=512,
        pattern=r"^[^\s@]+@sha256:[0-9a-f]{64}$",
    ),
]


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ManifestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Slug
    display_name: str = Field(min_length=2, max_length=100)
    version: SemanticVersion
    owner: str = Field(min_length=3, max_length=200)
    risk_tier: RiskTier


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = Field(min_length=1, max_length=500)
    commit_sha: SourceSha


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entrypoint: str = Field(min_length=3, max_length=300)
    image: ImageReference


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: Slug
    version: SemanticVersion


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Slug
    name: str = Field(min_length=1, max_length=200)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list, max_length=50)


class RetrievalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: Slug
    corpus_version: str = Field(min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=100)


class AgentManifestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceSpec
    runtime: RuntimeSpec
    prompt: PromptSpec
    model: ModelSpec
    tools: list[ToolSpec] = Field(default_factory=list, max_length=50)
    retrieval: RetrievalSpec | None = None


class AgentManifest(BaseModel):
    """Immutable executable specification registered by name and semantic version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/v1"]
    kind: Literal["AgentManifest"]
    metadata: ManifestMetadata
    spec: AgentManifestSpec

    @property
    def manifest_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json", by_alias=True, exclude_none=False),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
