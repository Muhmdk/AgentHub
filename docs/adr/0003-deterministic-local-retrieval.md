# ADR 0003: Use deterministic in-memory retrieval for local RAG

- Status: Accepted
- Date: 2026-09-08
- Owners: AgentHub maintainers

## Context

The Knowledge and Shopping Agents need measurable retrieval, stable citations, metadata
filtering, and repeatable ingestion. Phase 02 has only seven small synthetic documents and no
persistence requirement. Introducing PostgreSQL with pgvector or a hosted search service now
would add infrastructure and provider credentials before the registry phase establishes a real
database lifecycle.

Default tests must also run offline without paid embedding calls. A production search adapter
will eventually need to preserve the same evidence and version contracts, so agent code should
not depend on an embedding vendor or storage engine.

## Decision

Phase 02 uses an `InMemoryRetriever` behind a provider-neutral `Retriever` protocol. It applies
deterministic paragraph-and-word chunking, SHA-256 content hashes, and stable chunk identifiers.
Corpus identity is the pair of corpus ID and version. Re-ingesting an identical version reports
unchanged chunks; trying to change the contents of that version is rejected.

The local embedding model tokenizes normalized text and maps terms into a fixed 4,096-dimension
feature-hash vector. Cosine similarity produces deterministic rankings, with chunk ID as the
tie-breaker. Search accepts exact metadata filters and returns corpus identity, query, result
IDs, ranks, scores, and measured latency.

The agents accept the retrieval protocol rather than the concrete adapter. PostgreSQL/pgvector
or Azure AI Search may be added only when scale, persistence, or cloud deployment requirements
justify them, with contract tests proving equivalent filtering, versioning, and evidence
behavior.

## Consequences

Benefits:

- local ingestion, retrieval, demos, and tests need no database, cloud account, or network;
- content and chunk identities are reproducible and immutable within a corpus version;
- a committed known-answer suite can detect ranking regressions;
- future adapters have a narrow contract to implement.

Tradeoffs:

- all vectors and documents are rebuilt when a process starts;
- feature hashing is intentionally simple and does not provide semantic quality comparable to
  a production embedding model;
- latency measurements describe this tiny in-process corpus and are not capacity evidence;
- exact metadata filtering and linear scans will not scale to a large corpus.
