"""Deterministic local chunking, embedding, ingestion, and retrieval."""

import hashlib
import math
import re
import time
from collections import Counter
from typing import Protocol

from packages.contracts.retrieval import (
    Chunk,
    CorpusVersion,
    Document,
    Embedding,
    IngestionResult,
    RetrievalTrace,
    SearchRequest,
    SearchResult,
)
from packages.contracts.runtime import JsonValue

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "be",
        "can",
        "for",
        "i",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "what",
        "with",
        "within",
    }
)


def _tokens(text: str) -> list[str]:
    tokens = []
    for token in _TOKEN_PATTERN.findall(text.casefold()):
        if token in _STOP_WORDS:
            continue
        if len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s"):
            token = token[:-1]
        tokens.append(token)
    return tokens


def content_hash(content: str) -> str:
    """Hash normalized UTF-8 content for stable identity."""
    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return hashlib.sha256(normalized.encode()).hexdigest()


def create_document(
    *,
    document_id: str,
    title: str,
    content: str,
    metadata: dict[str, JsonValue] | None = None,
) -> Document:
    """Create a document whose hash always matches its content."""
    return Document(
        document_id=document_id,
        title=title,
        content=content,
        content_hash=content_hash(content),
        metadata=metadata or {},
    )


def chunk_document(document: Document, max_chars: int) -> list[Chunk]:
    """Split on paragraphs and words without unstable tokenizer dependencies."""
    if max_chars < 100:
        raise ValueError("Chunk size must be at least 100 characters")
    if document.content_hash != content_hash(document.content):
        raise ValueError("Document content hash does not match content")

    segments: list[str] = []
    for paragraph in re.split(r"\n\s*\n", document.content.strip()):
        words = paragraph.split()
        current: list[str] = []
        current_length = 0
        for word in words:
            added_length = len(word) + (1 if current else 0)
            if current and current_length + added_length > max_chars:
                segments.append(" ".join(current))
                current = [word]
                current_length = len(word)
            else:
                current.append(word)
                current_length += added_length
        if current:
            segments.append(" ".join(current))

    chunks = []
    for index, segment in enumerate(segments):
        segment_hash = content_hash(segment)
        chunks.append(
            Chunk(
                chunk_id=f"{document.document_id}:{index}:{segment_hash[:12]}",
                document_id=document.document_id,
                document_title=document.title,
                content=segment,
                content_hash=segment_hash,
                index=index,
                metadata=document.metadata,
            )
        )
    return chunks


class EmbeddingModel(Protocol):
    @property
    def name(self) -> str: ...

    def embed(self, chunk_id: str, text: str) -> Embedding: ...


class Retriever(Protocol):
    """Provider-neutral retrieval boundary used by grounded agents and tools."""

    def search(self, request: SearchRequest) -> tuple[list[SearchResult], RetrievalTrace]: ...


class DeterministicEmbeddingModel:
    """Offline signed feature-hashing embedding for small deterministic corpora."""

    name = "fake/hash-embedding-v1"

    def __init__(self, dimensions: int = 4096) -> None:
        if dimensions < 16:
            raise ValueError("Embedding dimensions must be at least 16")
        self._dimensions = dimensions

    def embed(self, chunk_id: str, text: str) -> Embedding:
        vector = [0.0] * self._dimensions
        counts = Counter(_tokens(text))
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode()).digest()
            bucket = int.from_bytes(digest[:4]) % self._dimensions
            vector[bucket] += count
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            vector = [value / magnitude for value in vector]
        return Embedding(chunk_id=chunk_id, model=self.name, values=vector)


class CorpusConflictError(RuntimeError):
    """Raised when callers try to mutate an existing corpus version."""


class InMemoryRetriever:
    """Small local retrieval adapter with immutable versioned corpus snapshots."""

    def __init__(self, embedding_model: EmbeddingModel | None = None) -> None:
        self._embedding_model = embedding_model or DeterministicEmbeddingModel()
        self._chunks: dict[tuple[str, str], dict[str, Chunk]] = {}
        self._embeddings: dict[tuple[str, str], dict[str, Embedding]] = {}

    def ingest(self, corpus: CorpusVersion, documents: list[Document]) -> IngestionResult:
        key = (corpus.corpus_id, corpus.version)
        proposed_chunks = {
            chunk.chunk_id: chunk
            for document in documents
            for chunk in chunk_document(document, corpus.chunk_size)
        }
        existing = self._chunks.get(key)
        if existing is not None and existing != proposed_chunks:
            raise CorpusConflictError("An existing corpus version cannot be changed")
        if existing is not None:
            return IngestionResult(
                corpus_id=corpus.corpus_id,
                corpus_version=corpus.version,
                document_count=len(documents),
                chunk_count=len(existing),
                added_chunks=0,
                unchanged_chunks=len(existing),
            )

        self._chunks[key] = proposed_chunks
        self._embeddings[key] = {
            chunk_id: self._embedding_model.embed(chunk_id, chunk.content)
            for chunk_id, chunk in proposed_chunks.items()
        }
        return IngestionResult(
            corpus_id=corpus.corpus_id,
            corpus_version=corpus.version,
            document_count=len(documents),
            chunk_count=len(proposed_chunks),
            added_chunks=len(proposed_chunks),
            unchanged_chunks=0,
        )

    def search(self, request: SearchRequest) -> tuple[list[SearchResult], RetrievalTrace]:
        started_at = time.perf_counter()
        key = (request.corpus_id, request.corpus_version)
        chunks = self._chunks.get(key)
        embeddings = self._embeddings.get(key)
        if chunks is None or embeddings is None:
            raise LookupError("Requested corpus version is not ingested")

        query_embedding = self._embedding_model.embed("query", request.query)
        scored: list[tuple[float, Chunk]] = []
        for chunk_id, chunk in chunks.items():
            if not all(
                chunk.metadata.get(name) == value for name, value in request.filters.items()
            ):
                continue
            score = sum(
                left * right
                for left, right in zip(
                    query_embedding.values, embeddings[chunk_id].values, strict=True
                )
            )
            if score > 0:
                scored.append((min(score, 1.0), chunk))

        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        results = [
            SearchResult(chunk=chunk, score=round(score, 6), rank=rank)
            for rank, (score, chunk) in enumerate(scored[: request.top_k], start=1)
        ]
        latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
        return results, RetrievalTrace(
            corpus_id=request.corpus_id,
            corpus_version=request.corpus_version,
            query=request.query,
            result_ids=[result.chunk.chunk_id for result in results],
            ranks=[result.rank for result in results],
            scores=[result.score for result in results],
            latency_ms=latency_ms,
        )
