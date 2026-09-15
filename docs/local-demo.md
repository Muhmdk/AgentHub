# Deterministic local demo

AgentHub can build a complete local walkthrough from committed synthetic retail data.
No Azure account is required, and no manual SQL or database editing is part of the
workflow.

## Start from a clean checkout

Install Docker and Python 3.14, then run:

```console
make demo
```

That one command creates the locked virtual environment; starts PostgreSQL, Collector,
Tempo, Prometheus, and Grafana; applies all migrations; safely resets known AgentHub
application tables; seeds the walkthrough; enables local OTLP export; and starts the API
at <http://127.0.0.1:8000>. Stop the API with Ctrl-C; stop the observability services with
`make observability-down`, then PostgreSQL with `make down`.

If dependencies are already installed and the API is running in another terminal,
recreate the exact walkthrough state with:

```console
make demo-reset
```

The reset refuses to run unless all of these are true:

- the environment is `local` or `test`;
- the model and retrieval providers are deterministic local adapters;
- the database is PostgreSQL on localhost and is named `agenthub`; and
- the applied migration is the exact schema revision expected by this checkout.

It truncates an explicit allowlist of AgentHub tables. It never drops a database,
schema, volume, or migration record.

## Seeded state

The command prints the generated identifiers and an explicit fixture notice. The
database then contains:

- three immutable agent manifests;
- an inventory evaluation that passes and a regressed comparison that fails;
- a production knowledge-agent release and an approved/staged candidate;
- a production route with a five-percent canary backed by 100 synthetic paired samples;
- one real policy-engine denial for an undeclared `admin.delete` tool; and
- one detected top-k regression incident with an immutable trigger and three evidence items.

Open the consoles:

- <http://127.0.0.1:8000/registry>
- <http://127.0.0.1:8000/evaluations>
- <http://127.0.0.1:8000/governance>
- <http://127.0.0.1:8000/observability>
- <http://127.0.0.1:8000/delivery>
- <http://127.0.0.1:8000/incidents-console>

## Truthful data boundaries

All seeded retail inputs, evaluation outputs, release attestations, shadow comparisons,
and top-k fault signals are synthetic fixtures. They exercise the production services
and persistence paths, but they are not claims about a real deployment, security scan,
customer workload, model bill, or outage. IDs and timestamps are generated on each
reset. The logical story and gate outcomes are deterministic.

The observability console is intentionally not pre-populated: it shows measurements
recorded by the current API process. Likewise, the cost table remains empty until the
current process records model usage. The delivery console's rate-card recommendation
is labelled as an illustrative projection.
