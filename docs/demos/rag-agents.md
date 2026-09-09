# RAG agent demonstrations

Phase 02 adds a seven-document fictional retail corpus, deterministic local retrieval, and two
grounded agents. Every default path is offline and uses the fake model.

## Validate ingestion

```bash
make ingest-corpus
```

The command loads `data/synthetic/corpus.json`, derives each SHA-256 content hash and stable
chunk ID, and ingests the documents twice into one local adapter. Its JSON report shows seven
chunks added initially and zero added on the repeated ingestion. Changing content while keeping
the same corpus ID and version is rejected instead of silently mutating the snapshot.

## Knowledge Agent

```bash
make demo-knowledge
```

The reference question is:

```text
Can I return an unopened product after 20 days?
```

The agent searches only documents whose metadata marks them as trusted policies. It returns the
30-day rule with the stable source identifier for “Returns and exchanges.” If no result clears
the configured evidence threshold, it returns `Insufficient evidence in the current policy
corpus.` with no citations.

To ask a different question:

```bash
.venv/bin/python -m agents.knowledge 'How long does standard Canadian shipping take?'
```

## Shopping Agent

```bash
make demo-shopping
```

The reference query asks for a snow shovel under $50. The agent invokes only the declared,
read-only `product.search` tool, applies the parsed price ceiling, and recommends the retrieved
NorthPeak shovel at $39.99. A budget that excludes every retrieved product produces an explicit
insufficient-evidence response; the agent cannot purchase, reserve, or modify products.

To use a different budget:

```bash
.venv/bin/python -m agents.shopping 'Recommend a snow shovel under $70' --seed 4
```

## HTTP invocation

Start the service with `make run`, then call either endpoint:

```bash
curl -s http://127.0.0.1:8000/agents/knowledge/invoke \
  -H 'Content-Type: application/json' \
  -d '{"query":"Can I return an unopened product after 20 days?","seed":7}'

curl -s http://127.0.0.1:8000/agents/shopping/invoke \
  -H 'Content-Type: application/json' \
  -d '{"query":"Recommend a snow shovel under $50","seed":7}'
```

Responses contain the normalized agent fields plus `retrieval`: corpus ID and version, query,
result chunk IDs, ranks, scores, and latency. Citations are drawn from those retrieved chunk
IDs. The Shopping response also records its `product.search` tool evidence.

## Retrieval benchmark

```bash
make benchmark-rag
```

The committed `retrieval-v1` suite contains six known-answer queries covering all three policies
and three product needs. The Phase 02 baseline is 6/6 top-three hits, or a `1.0` hit rate. The
command prints a machine-readable JSON report with every expected and retrieved document ID.

## Provenance and safety

The product and policy text was authored for AgentHub, contains no real retailer, manufacturer,
customer, or employee data, and is covered by the repository MIT license. Provenance is also
recorded beside the fixtures in `data/synthetic/README.md`.

Retrieved content is treated as untrusted data. Only documents marked `trusted: true` are
eligible, known embedded-instruction phrases are quarantined, and the model system message says
not to follow document instructions. Tests include malicious retrieved text and assert that it
cannot replace the prepared grounded answer.

## Limitations

- The feature-hash embedding is a deterministic test adapter, not a production semantic model.
- The in-memory index is rebuilt at process start and performs a linear scan over seven chunks.
- Prompt-injection phrase detection is a defense-in-depth fixture, not a complete content
  security classifier.
- The benchmark measures retrieval hit rate only; it is not an answer-quality, latency, load, or
  safety evaluation suite.
- Corpus changes require a new version. Persistent storage and production search adapters are
  intentionally deferred.
