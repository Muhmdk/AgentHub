# HTTP API reference

The running service publishes its exact OpenAPI contract and interactive documentation
at `/openapi.json` and `/docs`. This guide summarizes authentication, retry semantics,
endpoint families, and representative calls. Pydantic response models and the generated
OpenAPI document are authoritative for field-level schemas.

## Base URLs and authentication

Local development uses `http://127.0.0.1:8000`. Local and test modes provide explicit
deprecated `/agents/*` compatibility routes. Staging and production do not mount those
routes.

`/health/live`, `/health/ready`, and `/version` are public. In staging and production,
all other API and console paths require both headers:

```http
Authorization: Bearer <configured service token>
X-AgentHub-Identity: service/release-controller
```

The claimed identity must own that token. Gateway invocation enforces the same identity
and passes it into model/tool policy decisions. Tokens belong in a secret store or
environment variable, never a URL, shell history, manifest, or log.

Every request may include `X-Correlation-ID` using 1–128 letters, numbers, `.`, `_`, `:`,
or `-`. AgentHub returns the accepted/generated value. Release-aware clients may include
`X-AgentHub-Release-ID` with the same bounded format.

## Endpoint families

| Family | Methods and paths | Purpose |
| --- | --- | --- |
| Health | `GET /health/live`, `/health/ready`, `/version` | process health, dependency/schema readiness, build metadata |
| Gateway | `POST /gateway/agents/{agent_name}/invoke` | authenticated and governed agent execution |
| Local agents | `POST /agents/{inventory,knowledge,shopping}/invoke` | local/test compatibility execution only |
| Registry | `POST /registry/agents`; `GET /registry/agents`, `/{name}`, `/{name}/versions`, `/{name}/versions/{version}`, `/{name}/versions/{version}/audit`; `POST .../transitions` | immutable manifests and lifecycle audit |
| Evaluation | `POST /evaluations/runs`; `GET /evaluations/runs`, `/{run_id}`, `/{run_id}/comparison` | execute, list, replay, and compare evaluation artifacts |
| Release | `POST /releases/candidates`, `/{release_id}/transitions`; `GET /releases`, `/{release_id}`, `/{release_id}/events`, `/{release_id}/notes` | evidence-bound candidate and promotion lifecycle |
| Delivery | `POST/GET /delivery/routes`; `GET/PUT /delivery/routes/{route_id}`; `GET .../events`; `POST/GET /delivery/canaries`; `GET /delivery/canaries/{id}`, `.../events`; `POST .../actions`, `/delivery/guardrails/preview`, `/delivery/cost-recommendation`; `GET /delivery/costs`, `/delivery/overview` | atomic routing, shadow/canary controls, observed costs, projections |
| Governance | `GET /governance/policy`, `/governance/audit` | active safe policy view and sanitized decision history |
| Observability | `GET /observability/fleet`, `/observability/agents/{name}` | in-process measurements, SLO status, error-budget burn, trace link |
| Incidents | `POST /incidents/signals`; `GET /incidents`, `/{id}`, `/{id}/triggers`, `/{id}/evidence`, `/{id}/timeline`, `/{id}/investigation`; `POST /incidents/{id}/evidence`, `/{id}/rollback` | detection, evidence, cited investigation, policy-bound recovery |

Operator HTML is served at `/registry`, `/evaluations`, `/delivery`, `/governance`,
`/observability`, and `/incidents-console` and is intentionally excluded from OpenAPI.

## Errors and retries

Errors have one safe envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "correlation_id": "demo-request-1",
    "details": []
  }
}
```

Submitted values, provider response bodies, database details, and credentials are not
echoed. Common statuses are `400` invalid operation, `401` authentication required,
`404` missing resource, `409` revision/idempotency conflict, `422` schema validation,
`429` rate or budget exhaustion, `503` dependency/policy unavailable, and `504` bounded
provider timeout.

Mutating contracts include an `idempotency_key`; revisioned resources also require the
last observed revision. A retry must repeat the identical request and key. Reusing a key
for different input is a conflict. After a revision conflict, read the current resource,
decide whether the intended change is still valid, and submit a new key and revision.

## Examples

Invoke the local Inventory Agent:

```console
curl --fail-with-body http://127.0.0.1:8000/agents/inventory/invoke \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: inventory-example-1' \
  --data '{"query":"Which Toronto stores may run low on snow shovels this weekend?","seed":7,"as_of":"2026-09-08"}'
```

Register the committed manifest idempotently:

```console
curl --fail-with-body http://127.0.0.1:8000/registry/agents \
  -H 'Content-Type: application/json' \
  -H 'X-AgentHub-Actor: local/operator' \
  -H 'X-Correlation-ID: manifest-example-1' \
  --data-binary @data/manifests/inventory-agent-v1.json
```

Run an evaluation:

```console
curl --fail-with-body http://127.0.0.1:8000/evaluations/runs \
  -H 'Content-Type: application/json' \
  --data '{"agent_name":"inventory-agent","agent_version":"1.0.0","suite_id":"inventory-agent-suite","candidate_profile":"default","environment":"local"}'
```

Filter denied policy decisions:

```console
curl --fail-with-body 'http://127.0.0.1:8000/governance/audit?outcome=deny&limit=20'
```

For the complete lifecycle payloads, use the generated `/docs` page after `make demo`.
Committed manifest, dataset, suite, and gate examples are indexed in
[examples/README.md](examples/README.md).
