# Agent manifests and lifecycle

Phase 03 introduces the persistent AgentHub registry. An agent is a stable logical name; each
semantic version is an immutable executable specification described by an Agent Manifest.

## Start the registry locally

```bash
make setup
make up
make migrate
make seed-registry
make run
```

Open `http://127.0.0.1:8000/registry` for the inventory view or
`http://127.0.0.1:8000/docs` for interactive API documentation. Stop the foreground API with
`Ctrl-C`, then use `make down` to stop PostgreSQL. The named database volume remains available
for the next run.

`make seed-registry` loads all JSON files from `data/manifests/`. Running it again returns the
existing version identifiers and creates no duplicates or extra audit events.

## Manifest identity

The published contract is `schemas/agent-manifest-v1.schema.json`. Pydantic applies the same
runtime rules. A manifest records:

- schema version, agent name, semantic version, display name, owner, and risk tier;
- repository and exact 40-character source commit SHA;
- runtime entry point and OCI image reference pinned with a SHA-256 digest;
- prompt ID/version and provider-neutral model configuration;
- declared tools and their scopes;
- optional retrieval corpus version and top-k configuration.

Unknown fields and schema versions are rejected. Mutable image tags and branch names cannot
replace the required image digest and source SHA. The manifest hash is SHA-256 over canonical,
sorted compact JSON, so harmless key ordering does not change identity.

The three committed example manifests describe Inventory, Knowledge, and Shopping Agent version
`1.0.0` at the green `v0.1.0` source commit. Their image digests demonstrate the immutable
contract; they do not claim that images were published by Phase 03.

## Register and inspect a version

```bash
curl -s http://127.0.0.1:8000/registry/agents \
  -H 'Content-Type: application/json' \
  -H 'X-AgentHub-Actor: local-operator' \
  -H 'X-Correlation-ID: register-inventory-1' \
  --data-binary @data/manifests/inventory-agent-v1.json

curl -s http://127.0.0.1:8000/registry/agents
curl -s http://127.0.0.1:8000/registry/agents/inventory-agent/versions
curl -s http://127.0.0.1:8000/registry/agents/inventory-agent/versions/1.0.0/audit
```

The registration response contains `created` and the complete stored version. Registering the
same manifest again returns `created: false`. Reusing `inventory-agent` version `1.0.0` with a
different source, image, prompt, model, tool, retrieval, owner, or risk value returns HTTP `409`.

## Lifecycle transitions

Every new version begins in `draft` at state revision `1`. Legal next states are:

| Current state | Legal next states |
|---|---|
| `draft` | `registered`, `retired` |
| `registered` | `evaluating`, `retired` |
| `evaluating` | `approved`, `rejected`, `retired` |
| `approved` | `staged`, `retired` |
| `rejected` | `evaluating`, `retired` |
| `staged` | `canary`, `rolled_back`, `retired` |
| `canary` | `production`, `rolled_back`, `retired` |
| `production` | `rolled_back`, `retired` |
| `rolled_back` | `staged`, `retired` |
| `retired` | None; this state is terminal |

Self-transitions and shortcuts are conflicts. Clients send the revision they read; a concurrent
state change increments that revision and causes the stale request to fail rather than overwrite
new state.

```bash
curl -s http://127.0.0.1:8000/registry/agents/inventory-agent/versions/1.0.0/transitions \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: register-inventory-state-1' \
  -d '{"target_state":"registered","actor":"local-operator","reason":"Manifest reviewed","expected_revision":1}'
```

## Audit and failure behavior

Registration and transition audit rows are inserted in the same transaction as their registry
change. Each records actor, UTC time, prior and new state, request correlation ID, manifest hash,
and an optional reason. PostgreSQL rejects audit updates and deletes.

Missing registry resources return the standard `registry_not_found` envelope with HTTP `404`.
Manifest reuse, illegal transitions, and stale revisions return `registry_conflict` with HTTP
`409`. Validation errors remain HTTP `422`. Submitted manifests and database details are not
included in error messages.

The actor value is not an authenticated identity in Phase 03. Authentication, authorization,
and policy-bound actor claims arrive in later governance work; callers must not treat this local
demo field as proof of identity.
