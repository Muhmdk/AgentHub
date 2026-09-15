# AgentHub architecture

AgentHub is a modular-monolith control plane. One FastAPI process composes bounded agent
runtimes and focused domain packages; PostgreSQL owns durable control-plane state. The
same contracts support deterministic local adapters and explicitly configured Azure
adapters. This document describes implemented behavior unless a section says **Reference
Azure deployment** or **Future**.

## System context

```mermaid
flowchart LR
    Operator[Operator or release workflow]
    Caller[Application caller]
    Hub[AgentHub API and AI Gateway]
    DB[(PostgreSQL)]
    Policy[Local policy engine or OPA]
    Providers[Local deterministic or Azure providers]
    Telemetry[OTel collector or Azure Monitor]

    Operator -->|registry, evaluation, release, delivery, incident| Hub
    Caller -->|authenticated agent invocation| Hub
    Hub -->|transactions and append-only evidence| DB
    Hub -->|policy decision before model or tool| Policy
    Hub -->|bounded model and retrieval calls| Providers
    Hub -->|redacted traces and metrics| Telemetry
```

The Gateway is the data-plane entry point for agent execution. Registry, evaluation,
release, delivery, observability, governance, and incident endpoints are control-plane
surfaces. In staging and production, every non-health surface requires a bearer token
whose configured service identity matches `X-AgentHub-Identity`.

## Runtime components

```mermaid
flowchart TB
    subgraph Process[FastAPI process]
        Middleware[Correlation, authentication, safe errors]
        Gateway[Governed AI Gateway]
        Agents[Inventory, Knowledge, Shopping agents]
        Domains[Registry, evaluation, release, delivery, incident services]
        Obs[Telemetry, SLO, cost aggregation]
        Adapters[Provider adapters]
        Middleware --> Gateway --> Agents
        Middleware --> Domains
        Agents --> Adapters
        Agents --> Obs
        Domains --> Obs
    end

    DB[(PostgreSQL)]
    OPA[OPA policy API]
    Model[Fake model or Azure OpenAI]
    Search[Local retrieval or Azure AI Search]
    OTEL[OTLP or Azure Monitor]

    Domains --> DB
    Gateway --> OPA
    Adapters --> Model
    Adapters --> Search
    Obs --> OTEL
```

Packages under `packages/` own contracts and domain behavior. `apps/api/main.py` is the
composition root and HTTP transport. Agents depend on narrow model, retrieval, tool,
database, policy, and telemetry protocols rather than SDK clients. Synchronous database
work runs behind explicit thread boundaries at async endpoints.

## Governed invocation sequence

```mermaid
sequenceDiagram
    participant C as Caller
    participant G as Gateway
    participant P as Policy engine
    participant A as Agent runtime
    participant T as Tool or model
    participant E as Audit and telemetry

    C->>G: Bearer token, claimed identity, bounded request
    G->>G: Authenticate and attach correlation context
    G->>P: Sanitized policy input
    P-->>G: Versioned allow or deny with obligations
    G->>E: Append decision
    alt denied, unavailable, or over budget
        G-->>C: Stable safe error
    else allowed
        G->>A: Invoke with deadline and release context
        A->>P: Authorize each model and tool action
        P-->>A: Obligations
        A->>T: Bounded operation after authorization
        T-->>A: Typed result or normalized failure
        A->>E: Redacted spans, metrics, cost, citations
        A-->>C: Typed response and evidence
    end
```

Policy and required audit failures fail closed. Prompts, model content, raw tool
arguments, credentials, and PII are not telemetry attributes. See the
[threat model](security/threat-model.md) for trust boundaries and residual risks.

## Release and recovery lifecycle

```mermaid
stateDiagram-v2
    [*] --> Evaluated
    Evaluated --> Approved: evaluation, scan, policy pass
    Evaluated --> Rejected: gate fails
    Approved --> Staged
    Staged --> Production: protected approval
    Production --> ShadowCandidate: immutable candidate route
    ShadowCandidate --> Canary5: paired guardrails pass
    Canary5 --> Canary25: guardrails pass
    Canary25 --> Canary50: guardrails pass
    Canary50 --> Canary100: guardrails pass
    Canary100 --> Completed
    Canary5 --> RolledBack: abort or incident policy
    Canary25 --> RolledBack: abort or incident policy
    Canary50 --> RolledBack: abort or incident policy
    RolledBack --> Recovered: fixed observation window passes
    RolledBack --> Escalated: recovery fails or is incomplete
```

Candidate provenance, route targets, incident evidence, and rollback commands reference
immutable releases. State changes use optimistic revisions and idempotency keys, while
events are append-only. A rollback restores the stored known-good target atomically; it
does not rebuild an image or rewrite an evaluation.

## Persistence ownership

| Domain | Durable records | Mutation rule |
| --- | --- | --- |
| Registry | agents, versions, lifecycle audit | version content immutable; state transition is revision guarded |
| Evaluation | runs, cases, metrics, gate decisions | report graph append-only |
| Release | candidates, provenance, release events | evidence immutable; legal state transitions only |
| Governance | sanitized decision/enforcement events | append-only; required audit fails closed |
| Delivery | route snapshots, canaries, route/action events | allocation replacement and canary action are atomic and revision guarded |
| Incident | triggers, content-addressed evidence, rollback/recovery events | evidence and events append-only; operation state is policy constrained |

Alembic is the only schema migration mechanism. Readiness requires connectivity and the
exact expected revision, preventing old application/database combinations from serving.

## Deployment views

### Implemented local deployment

```mermaid
flowchart LR
    Browser[Browser or curl] --> API[Python 3.14 API process]
    API --> PG[(Compose PostgreSQL)]
    API --> Fake[Deterministic fake model]
    API --> LocalSearch[In-process versioned retrieval]
    API -. optional .-> Collector[Collector, Tempo, Prometheus, Grafana]
```

The default path needs no cloud account or paid call. `make demo` provisions the local
dependencies, creates the synthetic walkthrough, and starts the API.

### Reference Azure deployment

The repository includes Terraform and Helm for AKS, Azure Database for PostgreSQL,
Azure OpenAI, Azure AI Search, Azure Monitor, Key Vault, workload identity, private
networking, and an OPA sidecar. CI validates these definitions but never provisions
Azure. Operators must review and apply infrastructure explicitly using the
[Azure deployment runbook](runbooks/azure-deploy.md).

### Future, not implemented

Multi-region active/active routing, an independently scaled data plane, automatic
provider failover, managed tenant administration, self-service policy authoring, and
external identity-directory integration are not implemented. A module becomes a
separate service only after measured isolation or scaling needs justify a new ADR.

## Related decisions

See the [ADR index](adr/README.md), [API reference](api.md),
[operator runbooks](runbooks/README.md), and [architecture audit](architecture-audit.md).
