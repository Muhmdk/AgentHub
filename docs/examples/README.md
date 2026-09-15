# Committed contract examples

These versioned files are executable inputs, not illustrative pseudocode:

| Contract | Example | Validation path |
| --- | --- | --- |
| Agent manifest | [`inventory-agent-v1.json`](../../data/manifests/inventory-agent-v1.json) | Pydantic `AgentManifest`, JSON Schema, registry constraints |
| Grounded RAG manifest | [`knowledge-agent-v1.json`](../../data/manifests/knowledge-agent-v1.json) | registry and governed runtime |
| Evaluation dataset | [`inventory-agent-v1.json`](../../data/evals/datasets/inventory-agent-v1.json) | dataset hash and case schemas |
| Evaluation suite | [`inventory-agent-suite-v1.json`](../../data/evals/suites/inventory-agent-suite-v1.json) | evaluator catalog and bounded runner |
| Release gate profile | [`default-v1.json`](../../data/evals/gates/default-v1.json) | absolute and baseline-relative gate engine |
| SLO profile | [`default-v1.json`](../../data/slos/default-v1.json) | fleet health and burn-rate calculation |
| Synthetic corpus | [`corpus.json`](../../data/synthetic/corpus.json) | versioned ingestion and retrieval benchmark |

Run them through production code paths:

```console
make seed-registry
make evaluate
make evaluate-bad
make simulate-release
```

`make demo-reset` recreates a linked pass/fail evaluation, two immutable releases, one
route/canary, a real policy denial, and one fault-labelled incident. Generated UUIDs and
timestamps differ on each reset; hashes, logical outcomes, and synthetic inputs remain
reproducible. See the [local demo guide](../local-demo.md) for truthful data boundaries.

The [HTTP API guide](../api.md) includes curl examples. The live `/openapi.json` document
is the authoritative JSON-schema view of request and response bodies.
