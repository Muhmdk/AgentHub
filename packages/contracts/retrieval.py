"""Versioned contracts for deterministic retrieval and grounded responses."""

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.runtime import AgentResponse, JsonValue, NonEmptyString


class Document(BaseModel):
    """Source document with stable identity and verified content hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: NonEmptyString
    title: NonEmptyString
    content: NonEmptyString
    content_hash: NonEmptyString
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Chunk(BaseModel):
    """Deterministically derived document segment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: NonEmptyString
    document_id: NonEmptyString
    document_title: NonEmptyString
    content: NonEmptyString
    content_hash: NonEmptyString
    index: int = Field(ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Embedding(BaseModel):
    """Provider-neutral vector attached to one chunk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: NonEmptyString
    model: NonEmptyString
    values: list[float] = Field(min_length=1)


class CorpusVersion(BaseModel):
    """Immutable corpus ingestion contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: NonEmptyString
    version: NonEmptyString
    chunk_size: int = Field(default=500, ge=100, le=4000)


class IngestionResult(BaseModel):
    """Repeatable ingestion outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: NonEmptyString
    corpus_version: NonEmptyString
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    added_chunks: int = Field(ge=0)
    unchanged_chunks: int = Field(ge=0)


class SearchRequest(BaseModel):
    """Bounded semantic search request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: NonEmptyString
    corpus_id: NonEmptyString
    corpus_version: NonEmptyString
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, JsonValue] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """One ranked retrieval result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk: Chunk
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)


class RetrievalTrace(BaseModel):
    """Evidence needed to reproduce and inspect one retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: NonEmptyString
    corpus_version: NonEmptyString
    query: NonEmptyString
    result_ids: list[NonEmptyString]
    ranks: list[int]
    scores: list[float]
    latency_ms: float = Field(ge=0.0)


class GroundedAgentResponse(AgentResponse):
    """Agent response augmented with reproducible retrieval metadata."""

    retrieval: RetrievalTrace


class RetrievalBenchmarkCase(BaseModel):
    """One known-answer query in a versioned retrieval benchmark."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyString
    query: NonEmptyString
    filters: dict[str, JsonValue] = Field(default_factory=dict)
    expected_document_id: NonEmptyString


class RetrievalBenchmarkResult(BaseModel):
    """Outcome of one known-answer retrieval case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyString
    expected_document_id: NonEmptyString
    result_document_ids: list[NonEmptyString]
    hit: bool


class RetrievalBenchmarkReport(BaseModel):
    """Machine-readable aggregate retrieval benchmark."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_version: NonEmptyString
    corpus_id: NonEmptyString
    corpus_version: NonEmptyString
    case_count: int = Field(ge=0)
    hit_count: int = Field(ge=0)
    hit_rate: float = Field(ge=0.0, le=1.0)
    results: list[RetrievalBenchmarkResult]
