"""Unit tests for the committed versioned retail corpus."""

import json
from pathlib import Path

import pytest

from agents.shared.corpus import create_retail_retriever, load_retail_corpus
from packages.contracts.retrieval import SearchRequest


@pytest.mark.unit
def test_corpus_loads_with_unique_hashed_documents() -> None:
    corpus, documents = load_retail_corpus()

    assert corpus.corpus_id == "retail-products-policies"
    assert corpus.version == "v1"
    assert len(documents) == 7
    assert len({document.document_id for document in documents}) == 7
    assert all(len(document.content_hash) == 64 for document in documents)
    assert all(document.metadata["source"] == "synthetic-agenthub" for document in documents)


@pytest.mark.unit
def test_default_retriever_ingests_complete_corpus() -> None:
    retriever, corpus, ingestion = create_retail_retriever()

    assert ingestion.document_count == 7
    assert ingestion.chunk_count == 7
    results, _ = retriever.search(
        SearchRequest(
            query="unopened products returned",
            corpus_id=corpus.corpus_id,
            corpus_version=corpus.version,
            filters={"kind": "policy"},
        )
    )
    assert results[0].chunk.document_id == "policy-returns-v1"


@pytest.mark.unit
def test_corpus_loader_rejects_duplicate_document_ids(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.json"
    payload = {
        "corpus": {"corpus_id": "test", "version": "v1", "chunk_size": 500},
        "documents": [
            {
                "document_id": "duplicate",
                "title": "One",
                "content": "First content",
                "metadata": {},
            },
            {
                "document_id": "duplicate",
                "title": "Two",
                "content": "Second content",
                "metadata": {},
            },
        ],
    }
    corpus_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be unique"):
        load_retail_corpus(corpus_path)
