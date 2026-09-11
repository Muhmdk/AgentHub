# AgentHub threat model

## Scope and assets

This model covers the API, AI Gateway, agent runtime, registry, evaluations, releases, progressive
delivery, incidents, rollback automation, PostgreSQL, OpenTelemetry pipeline, GitHub Actions, AKS
reference deployment, and Azure provider adapters. Protected assets are service identities,
credentials, prompts and user data, tool permissions, immutable manifests and provenance, policy
decisions, release/route state, incident evidence, and append-only audit history.

Trust boundaries are external callers to HTTP, the gateway to models/tools, the application to OPA
and provider APIs, the application to PostgreSQL and telemetry, GitHub Actions to Azure through OIDC,
and operators to deployment/rollback controls.

## Threats and controls

| Threat | Impact | Implemented controls | Residual risk |
|---|---|---|---|
| Identity spoofing or gateway bypass | Unauthorized agent or control-plane use | Constant-time bearer validation; explicit local identities only in local/test; legacy invocation routes absent outside local/test; every non-public staging/production route now requires the same configured identity | Shared service tokens are less granular than workload identity; rotate and scope them at ingress |
| Prompt injection | Model follows untrusted instructions or requests undeclared tools | Prompt-injection detection, bounded system instructions, typed tool calls, declared read scopes, step/time limits, output grounding | Novel semantic attacks may evade deterministic detection; keep write tools unavailable |
| Retrieval poisoning | Incorrect or malicious evidence reaches answers | Versioned corpus, content hashes, deterministic chunking, score floor, citations, ingestion replay, known-answer benchmark | Authorized corpus publishers can add misleading content; publication approval is external |
| Tool abuse | Data mutation or cross-agent access | Per-agent allowlists, typed arguments, OPA scopes, read-only demo tools, bounded execution, audit events | Future write tools require a separate threat review and stronger operator authorization |
| PII or credential leakage | Sensitive values reach providers, logs, errors, or evidence | Pre-provider PII detection/redaction, sanitized metrics/logs, safe error envelopes, bounded attributes, secret scanning | Free-form text can contain unrecognized sensitive data; external-provider use remains opt-in |
| Dependency or image compromise | Malicious build/runtime code | Locked dependencies, dependency audit, digest-pinned images/actions, SBOM, provenance, image scanning, protected promotion | Zero-day vulnerabilities and compromised upstream attestations remain possible |
| CI credential theft | Cloud or repository compromise | GitHub OIDC, short-lived Azure tokens, protected environments, least privilege, no committed secrets | GitHub/Azure control-plane compromise is outside the repository boundary |
| Policy outage or bypass | Requests execute without authorization | OPA fails closed, local engine only by explicit local configuration, decision audits, policy tests, network policy | A privileged cluster operator can replace policy/configuration; infrastructure admin is trusted |
| Rollback abuse | Attacker redirects production or repeats destructive recovery | Authenticated production control plane; actor/identity match; server-derived evidence, guardrail, canary, concurrency and risk facts; immutable known-good lineage; command hash; optimistic revisions; idempotency; cooldown; attempt cap; append-only audit | Service-token holders can approve manual rollback; independent human approval is process-enforced until identity roles are added |
| Evidence tampering | False incident conclusion or hidden history | Content hashes, immutable identity fields, append-only triggers/evidence/events, source citations, clock-skew and contradiction warnings | Database superusers can bypass application roles and triggers; database administration is trusted and audited externally |
| Resource exhaustion | Availability loss or cost spike | Request/token/cost budgets, bounded queues, timeouts, retries, model steps, evidence sizes, API validation, Kubernetes requests/limits | Horizontal distributed rate limiting is not implemented; per-process limits are explicit |

## High-risk findings closed

1. **Unauthenticated production control plane:** before Phase 11, gateway invocation was authenticated
   but registry, delivery, evidence, and rollback routes relied on network placement. All non-public
   staging and production paths now require configured bearer identity.
2. **Rollback actor spoofing:** rollback audit actors could differ from the authenticated caller.
   Staging/production rollback now requires an exact actor/subject match.
3. **Client-asserted rollback eligibility:** already closed in Phase 10. The rollback endpoint rejects
   extra policy facts and derives them from persisted evidence and delivery state.

## Accepted residual risks

- Control-plane service tokens do not yet encode roles or independent approval claims. Restrict the
  rollback-capable identity at the ingress and keep the documented two-person production process.
- PostgreSQL administrators and Kubernetes/Azure administrators are trusted. Native platform audit,
  access reviews, and break-glass procedures remain deployment-owner responsibilities.
- Local deterministic safety checks are defense in depth, not a substitute for provider safety
  controls or adversarial red-team testing against the selected production model.
- Rate, token, and cost budgets are process-local. Multi-replica production needs a shared limiter
  before increasing public traffic.
- Backup scheduling and restore infrastructure depend on the deployment environment; the repository
  supplies verification procedures but does not create or retain production backups automatically.

Revisit this model whenever a write-capable tool, public ingress, new identity provider, shared
limiter, external corpus publisher, or automatic stable-production rollback is introduced.
