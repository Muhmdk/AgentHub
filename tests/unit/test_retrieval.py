"""Unit tests for deterministic local ingestion and retrieval."""

import pytest

from agents.shared.retrieval import (
    CorpusConflictError,
    DeterministicEmbeddingModel,
    InMemoryRetriever,
    chunk_document,
    create_document,
)
from packages.contracts.retrieval import CorpusVersion, Document, SearchRequest


@pytest.fixture
def documents() -> list[Document]:
    return [
        create_document(
            document_id="policy-returns",
            title="Returns policy",
            content="Unopened items may be returned within 30 days with the original receipt.",
            metadata={"kind": "policy", "topic": "returns"},
        ),
        create_document(
            document_id="product-shovel",
            title="Snow shovel",
            content="The NorthPeak snow shovel has an aluminum blade and costs 39.99 dollars.",
            metadata={"kind": "product", "sku": "snow-shovel", "price": 39.99},
        ),
    ]


@pytest.mark.unit
def test_chunking_is_stable_and_bounded() -> None:
    document = create_document(
        document_id="long-doc",
        title="Long document",
        content=("alpha " * 30) + "\n\n" + ("beta " * 30),
    )

    first = chunk_document(document, max_chars=100)
    second = chunk_document(document, max_chars=100)

    assert first == second
    assert len(first) == 4
    assert all(len(chunk.content) <= 100 for chunk in first)
    assert len({chunk.chunk_id for chunk in first}) == 4


@pytest.mark.unit
def test_chunking_rejects_invalid_size_and_stale_hash(documents: list[Document]) -> None:
    with pytest.raises(ValueError, match="at least 100"):
        chunk_document(documents[0], max_chars=99)

    stale = documents[0].model_copy(update={"content_hash": "stale"})
    with pytest.raises(ValueError, match="does not match"):
        chunk_document(stale, max_chars=500)


@pytest.mark.unit
def test_embedding_is_deterministic_and_normalized() -> None:
    model = DeterministicEmbeddingModel(dimensions=32)

    first = model.embed("chunk-1", "snow shovel snow")
    second = model.embed("chunk-1", "snow shovel snow")

    assert first == second
    assert sum(value * value for value in first.values) == pytest.approx(1.0)


@pytest.mark.unit
def test_embedding_rejects_tiny_dimensions() -> None:
    with pytest.raises(ValueError, match="at least 16"):
        DeterministicEmbeddingModel(dimensions=8)


@pytest.mark.unit
def test_ingestion_is_idempotent(documents: list[Document]) -> None:
    retriever = InMemoryRetriever()
    corpus = CorpusVersion(corpus_id="retail", version="v1")

    first = retriever.ingest(corpus, documents)
    second = retriever.ingest(corpus, documents)

    assert first.document_count == 2
    assert first.added_chunks == 2
    assert second.added_chunks == 0
    assert second.unchanged_chunks == 2


@pytest.mark.unit
def test_existing_corpus_version_is_immutable(documents: list[Document]) -> None:
    retriever = InMemoryRetriever()
    corpus = CorpusVersion(corpus_id="retail", version="v1")
    retriever.ingest(corpus, documents)
    changed = [
        create_document(
            document_id="policy-returns",
            title="Returns policy",
            content="Changed policy content.",
            metadata={"kind": "policy"},
        )
    ]

    with pytest.raises(CorpusConflictError, match="cannot be changed"):
        retriever.ingest(corpus, changed)


@pytest.mark.unit
def test_search_ranks_known_answer_and_applies_metadata_filter(
    documents: list[Document],
) -> None:
    retriever = InMemoryRetriever()
    corpus = CorpusVersion(corpus_id="retail", version="v1")
    retriever.ingest(corpus, documents)

    results, trace = retriever.search(
        SearchRequest(
            query="Can I return an unopened item?",
            corpus_id="retail",
            corpus_version="v1",
            top_k=2,
            filters={"kind": "policy"},
        )
    )

    assert [result.chunk.document_id for result in results] == ["policy-returns"]
    assert results[0].rank == 1
    assert results[0].score > 0
    assert trace.result_ids == [results[0].chunk.chunk_id]
    assert trace.ranks == [1]
    assert trace.scores == [results[0].score]
    assert trace.latency_ms >= 0


@pytest.mark.unit
def test_search_fails_for_unknown_corpus() -> None:
    with pytest.raises(LookupError, match="not ingested"):
        InMemoryRetriever().search(
            SearchRequest(query="returns", corpus_id="missing", corpus_version="v1")
        )
