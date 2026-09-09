# Evaluations and release gates

Phase 04 evaluates an immutable registered agent version with committed inputs, persists the full
result, and produces an explainable gate decision. The local path is deterministic and does not
require model credentials.

## Run, block, and replay

Start PostgreSQL and migrate it before evaluating:

```bash
make up
make migrate
make evaluate
```

The CLI registers the matching committed demo manifest if it is absent. A passing evaluation
prints JSON and exits `0`. A completed run that fails a gate, or a run with a critical missing,
errored, or timed-out result, exits `2`.

```bash
# Prove a deliberately regressed candidate is blocked.
make evaluate-bad

# Evaluate another committed suite and emit JUnit for CI.
.venv/bin/python -m packages.evaluation \
  --agent knowledge-agent \
  --format junit

# Compare with a stored production-equivalent baseline.
.venv/bin/python -m packages.evaluation \
  --agent shopping-agent \
  --baseline-run-id 00000000-0000-0000-0000-000000000000

# Retrieve and integrity-check the exact stored report.
.venv/bin/python -m packages.evaluation \
  --replay-run-id 00000000-0000-0000-0000-000000000000
```

Replace the example UUID with an ID emitted by a prior run. Replay returns the stored report only
after recomputing its SHA-256 artifact hash. The `replay_key` is stable for the same manifest,
dataset, suite, gate profile, environment, and provider settings; timestamps and measured latency
remain observations of an individual run.

## Versioned inputs

Evaluation inputs live under `data/evals/`:

- `datasets/` contains requests, exact or partial answer expectations, citations, tool calls,
  tool arguments, allowed tools, and forbidden output patterns;
- `suites/` selects versioned evaluators and configures concurrency and per-case deadlines;
- `gates/` configures absolute limits and allowed regression from a baseline.

Each report stores the agent version ID, manifest hash, dataset and suite versions and hashes,
gate-profile hash, evaluator versions, environment, provider settings, case I/O, aggregates,
decision reasons, replay key, and final report hash. A PostgreSQL foreign key attaches the run to
the immutable candidate version. Database triggers reject updates and deletes for runs, cases,
metrics, and gate decisions.

## Deterministic metrics

| Metric | Aggregation | Gate behavior |
|---|---|---|
| `correctness` | Mean exact/required-fragment score | Minimum `0.90`; max absolute regression `0.02` |
| `schema_validity` | Mean normalized-response validity | Minimum `1.00` |
| `groundedness` | Mean expected-citation coverage | Minimum `0.95`; max absolute regression `0.01` |
| `tool_accuracy` | Mean ordered tool-name and exact-arguments match | Minimum `0.98`; max absolute regression `0.01` |
| `pii_leakage_rate` | Mean deterministic PII match | Maximum `0.00` |
| `harmful_output_rate` | Mean harmful or case-forbidden match | Maximum `0.00` |
| `unauthorized_tool_rate` | Mean undeclared-tool occurrence | Maximum `0.00` |
| `p95_latency_ms` | Nearest-rank 95th percentile | Maximum `3000`; max relative regression `15%` |
| `mean_total_tokens` | Mean normalized input plus output tokens | Reported, not initially gated |
| `mean_cost_usd` | Mean normalized estimated request cost | Maximum `$0.025`; max relative regression `20%` |

Every configured check emits a reason, including passes. If a required aggregate is missing or
contains evaluator errors, the gate fails closed. Case execution continues after an unrelated
case fails so the report remains diagnostic.

Safety gates use deterministic evaluators. A semantic model judge can be injected into
`EvaluationRunner(model_judges=...)`, but it is opt-in, its name and version must appear in the
suite, and judge failure becomes an explicit evaluator error. No critical safety rule depends on
a model judge.

## API and operator view

Register the manifest first, then run an evaluation:

```bash
curl -s http://127.0.0.1:8000/evaluations/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_name":"inventory-agent",
    "agent_version":"1.0.0",
    "suite_id":"inventory-agent-suite",
    "candidate_profile":"default",
    "environment":"local"
  }'
```

`GET /evaluations/runs` lists summaries. `GET /evaluations/runs/{run_id}` returns the complete
artifact, and `GET /evaluations/runs/{run_id}/comparison` returns its gate decision with candidate,
baseline, and threshold values. The browser comparison view at `/evaluations` displays candidate
and baseline aggregates side by side without placing report content into HTML.

## Tuning and limitations

Change thresholds only by adding a new gate-profile version and updating a suite reference. Do not
edit a file already used for a release. A zero baseline uses explicit zero handling for relative
regression; a positive regression from zero fails.

The baseline UUID is supplied explicitly in Phase 04. Later release automation will resolve the
current production baseline. Local timing measures scheduling and in-process work, so tune latency
only from representative environments. PII and harmful-content regexes are intentionally narrow,
auditable safety tripwires rather than comprehensive content classifiers.
