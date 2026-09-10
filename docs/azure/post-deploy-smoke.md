# Post-deployment smoke verification

The same bounded verifier runs against a local process or a reachable Azure gateway. It checks:

1. liveness, readiness, and deployed version;
2. idempotent inventory-agent registration and registry lookup;
3. one inventory invocation, including tool and citation evidence;
4. one knowledge invocation, including retrieval-grounded citation evidence; and
5. the two-case inventory evaluation suite, requiring every case to complete.

The Azure path makes four bounded model requests in the normal case: the two direct invocations
and two inventory evaluation cases. Review the selected deployment's token rates and quota before
running it. The smoke report contains only service metadata, model identifiers, registry status,
evaluation ID, and gate result; it does not print prompts, response bodies, bearer tokens, or
provider endpoints.

## Local

Start PostgreSQL, migrate it, and start the API in another terminal. Then run:

```bash
make smoke-deployment \
  BASE_URL=http://127.0.0.1:8000 \
  SMOKE_ARGS="--expected-model-prefix fake/ --environment local-smoke"
```

Only `http://localhost` and `http://127.0.0.1` are accepted without TLS.

## Azure

From a workstation that can reach the gateway, port-forward the ClusterIP Service and run the
same local command with `--expected-model-prefix azure-openai/`. To exercise an externally
reachable gateway, use its HTTPS origin:

```bash
make smoke-deployment \
  BASE_URL=https://agenthub.example.com \
  SMOKE_ARGS="--expected-model-prefix azure-openai/ --environment azure-smoke"
```

The manually dispatched `Azure Post-Deploy Smoke` workflow runs in the protected `staging`
GitHub environment and accepts the same reachable HTTPS origin. If authentication is enabled,
store a short-lived, narrowly scoped token in the environment secret named
`AGENTHUB_SMOKE_BEARER_TOKEN`; the workflow passes it only as an Authorization header. Do not use
a long-lived API key.

The verifier registers the committed `inventory-agent` manifest. A repeated run is safe only when
that version has the same immutable manifest hash. A conflict means the deployed registry already
contains different content under the same version and should be investigated rather than
overwritten.
