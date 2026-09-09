"""Versioned loading and ingestion of the synthetic retail corpus."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from agents.shared.retrieval import InMemoryRetriever, create_document
from packages.contracts.retrieval import CorpusVersion, Document, IngestionResult
from packages.contracts.runtime import JsonValue


class CorpusDocumentSource(BaseModel):
    """Human-editable document fixture before its content hash is derived."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    title: str
    content: str
    metadata: dict[str, JsonValue]


class CorpusSource(BaseModel):
    """Complete on-disk corpus fixture contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus: CorpusVersion
    documents: list[CorpusDocumentSource]


def load_retail_corpus(path: Path | None = None) -> tuple[CorpusVersion, list[Document]]:
    """Load and hash the committed synthetic corpus."""
    corpus_path = path or Path(__file__).parents[2] / "data" / "synthetic" / "corpus.json"
    try:
        raw = json.loads(corpus_path.read_text(encoding="utf-8"))
        source = CorpusSource.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("Synthetic retail corpus is invalid") from exc

    document_ids = [document.document_id for document in source.documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Synthetic retail corpus document IDs must be unique")
    documents = [
        create_document(
            document_id=document.document_id,
            title=document.title,
            content=document.content,
            metadata=document.metadata,
        )
        for document in source.documents
    ]
    return source.corpus, documents


def create_retail_retriever() -> tuple[InMemoryRetriever, CorpusVersion, IngestionResult]:
    """Build the deterministic local adapter with the committed corpus ingested."""
    corpus, documents = load_retail_corpus()
    retriever = InMemoryRetriever()
    result = retriever.ingest(corpus, documents)
    return retriever, corpus, result
