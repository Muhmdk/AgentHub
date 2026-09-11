# Governance and AI Gateway

AgentHub places one authenticated gateway in front of agent invocation and applies policy again
immediately before each model or tool action. Prompt instructions and UI state are never treated
as authorization. Staging and production omit the legacy direct agent routes, so valid gateway
credentials cannot be replayed against an internal invocation path.

## Request and decision flow

```text
caller
  -> gateway authentication
  -> caller identity + correlation context
  -> agent planning
  -> typed model/tool policy input
  -> OPA decision
  -> append-only sanitized decision event
  -> redaction / budget / timeout enforcement
  -> provider or read-only tool
```

Local and test calls must send an explicit `X-AgentHub-Identity: local/<name>` header. Staging
and production accept a configured bearer credential for a named service identity. Tokens are
compared in constant time and are never placed in policy inputs, logs, telemetry, or audit rows.
The canonical endpoint is:

```text
POST /gateway/agents/{agent_name}/invoke
```

The authenticated identity, agent version, release ID, and correlation ID are propagated through
context variables to nested model and tool checks. The context is restored after each request, so
concurrent invocations cannot inherit another caller's identity.

## Policy contract

`packages/contracts/governance.py` defines a closed, versioned input and decision schema shared by
the application and OPA. Inputs cover registration, promotion, model invocation, and tool
execution. Model inputs contain provider, deployment, estimated token counts, and data classes;
they never contain messages. Tool inputs contain a SHA-256 arguments fingerprint, not arguments.

The reference Rego bundle enforces:

| Boundary | Reference behavior |
|---|---|
| deployed identity | rejects explicit local identities in staging and production |
| agent tools | requires the declared tool, access class, and every requested scope |
| write access | rejects write tools for low- and medium-risk registrations |
| model routing | requires the declared provider/deployment and environment allowlist |
| model size | allows at most 16,000 estimated input and 4,096 requested output tokens |
| production risk | requires one independent approval for low/medium, two for high, and rejects critical |
| evidence | requires passing evaluation and security gates before promotion |
| approval integrity | rejects duplicate, self, and future-dated approvals |
| PII | requires redaction when supported PII would leave the local process |

Run all policy tests with `make policy`. The CI policy job installs the checksum-pinned OPA
version and evaluates every allow, deny, exact-limit, and approval boundary offline.

## Runtime controls

The server decorates each configured model and tool. A deny or policy-engine failure stops before
the target is called. Unexpected policy adapter failures are also treated as unavailable; there
is no fail-open branch.

Supported PII detection covers email addresses, North American phone numbers, Luhn-valid payment
cards, and Luhn-valid Canadian SINs. Detection runs before policy evaluation, but only the `pii`
classification is sent to policy. Required redaction then replaces values with deterministic
typed markers before an external adapter sees the request. Finding records retain type and
offsets only.

Model capacity is reserved atomically before a provider call using a key of agent name, agent
version, provider, and model. The reservation includes the worst-case requested tokens and
configured input/output price. Provider-reported usage replaces the reservation on success;
token and cost capacity is released on failure while the request-rate event remains counted.
Rolling controls are configured with:

| Variable | Default |
|---|---:|
| `AGENTHUB_MODEL_REQUESTS_PER_MINUTE` | `120` |
| `AGENTHUB_MODEL_TOKENS_PER_MINUTE` | `100000` |
| `AGENTHUB_MODEL_COST_PER_HOUR_USD` | `10.0` |
| `AGENTHUB_MODEL_TIMEOUT_SECONDS` | `10.0` |
| `AGENTHUB_MODEL_MAX_ATTEMPTS` | `2` |
| `AGENTHUB_MODEL_RETRY_BACKOFF_SECONDS` | `0.05` |

Only throttling, server availability, network, and timeout failures are retryable. Retries use a
bounded exponential delay and never exceed three attempts. Client and response-validation errors
are not retried. Rate and budget denials return HTTP `429`; exhausted model timeouts return `504`.

Budget state is process-local. The reference chart defaults to one replica, making the configured
limits effective for that development deployment. Do not scale model-serving replicas above one
and claim a global budget; a later production design must use a shared atomic budget backend.

## Append-only audit

Every policy allow, policy deny, and policy outage is recorded before execution continues. A
second runtime-enforcement event records rate and budget violations that follow a policy allow.
If a required audit write fails, execution fails closed with `policy_unavailable`.

The `governance_audit_events` table records event ID/type/outcome, allowed status, identity, agent
and version, action and safe target, policy bundle version, reasons and obligations, time,
correlation/release IDs, and the typed sanitized policy input. It has no prompt, response, raw
tool arguments, credential, or matched PII field. PostgreSQL triggers reject updates and deletes.

Operators can query:

```text
GET /governance/policy
GET /governance/audit?agent_name=inventory-agent&outcome=deny&limit=100
```

The console at `http://127.0.0.1:8000/governance` shows the active enforcement posture, agent
grants, budgets, and newest sanitized events. Treat PostgreSQL as authoritative; console absence
is not evidence that an action was allowed.

## Failure behavior

| Failure | Response | Side effect |
|---|---|---|
| authentication missing or invalid | `401 authentication_required` | agent is not entered |
| policy deny | `403 policy_denied` | provider/tool is not called; deny is audited |
| policy or required audit unavailable | `503 policy_unavailable` | provider/tool is not called |
| rate or token/cost budget exhausted | `429 rate_limited` / `budget_exceeded` | provider is not called; violation is audited |
| model timeout after bounded attempts | `504 model_timeout` | reservation is released |

Internal exception text and submitted values are omitted from every response. Use the returned
correlation ID to locate the sanitized event. For an outage that requires operator intervention,
follow the [governance emergency runbook](runbooks/governance-emergency.md).
