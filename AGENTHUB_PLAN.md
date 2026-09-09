# AgentHub — Enterprise AgentOps & ModelOps Platform

> A production-grade control plane for registering, evaluating, deploying, observing, governing, and operating AI agents at scale.

**Repository:** `agenthub`  
**Primary stack:** Python, FastAPI, LangGraph, PostgreSQL, React/TypeScript, OpenTelemetry, Azure AI Foundry, Azure OpenAI, Azure AI Search, AKS, Helm, Terraform, GitHub Actions, OPA/Rego  
**Delivery model:** 12 phase branches, 12 reviewed pull requests, and frequent meaningful commits into a continuously working `main`

---

## 1. Purpose

AgentHub is an enterprise AgentOps and ModelOps control plane. It manages the production lifecycle of AI agents rather than being only another agent application.

Three deliberately small retail agents prove that the platform works:

- **Inventory Agent** — answers stock, demand, weather, and promotion questions from synthetic retail data.
- **Knowledge Agent** — answers policy and product questions with retrieval-augmented generation and citations.
- **Shopping Agent** — recommends products through retrieval and read-only tools.

The platform around those agents is the project. AgentHub provides:

- agent and version registration;
- immutable deployment lineage;
- offline evaluation and regression gates;
- CI/CD-driven promotion;
- end-to-end traces, metrics, logs, cost data, and SLOs;
- policy-as-code and runtime tool authorization;
- PII redaction, audit trails, and human approval gates;
- shadow evaluation and progressive canary delivery;
- cost-aware model routing;
- incident investigation with evidence;
- automated, policy-constrained rollback.

### Product statement

> AgentHub gives platform teams one place to deploy, evaluate, observe, govern, and safely roll back production AI agents.

### Resume title

**AgentHub | Python, Azure AI Foundry, LangGraph, AKS, Terraform, OpenTelemetry**

### Interview explanation

> AgentHub is an enterprise AgentOps control plane I built to manage the production lifecycle of AI agents, from registration and evaluation through deployment, observability, governance, incident investigation, and rollback.

---

## 2. Product boundaries

### In scope

- A working local-first platform with deterministic fake-model support.
- Three representative agents and synthetic retail data.
- A control-plane API, operator dashboard, and AI gateway.
- Versioned manifests, evaluations, policy decisions, releases, traces, incidents, and audit events.
- Azure reference infrastructure deployed to AKS by Terraform and Helm.
- A repeatable failure-and-rollback demonstration.

### Explicitly out of scope

- Training or fine-tuning foundation models.
- A general-purpose workflow builder or no-code agent studio.
- Multi-cloud parity.
- A custom service mesh, vector database, policy language, identity provider, or telemetry backend.
- Real customer data, real payment flows, or destructive tools.
- Dozens of demo agents or speculative microservices.
- Production-scale multi-tenancy, billing, or a marketplace.

### Anti-overengineering rules

1. Begin as a modular monolith. Extract a service only when an independently deployable boundary is demonstrated by load, security, or release needs.
2. Use one PostgreSQL database. Enable `pgvector` locally only when retrieval requires it.
3. Use proven standards: OpenTelemetry for telemetry, OPA/Rego for policy, OCI images, Helm for Kubernetes packaging, and Terraform for Azure.
4. Keep cloud adapters behind interfaces. Local development must work without Azure credentials or paid LLM calls.
5. Do not add Kafka, Redis, ClickHouse, Argo CD, Istio, service meshes, or extra databases until a measured requirement justifies them.
6. Do not create placeholder folders, empty modules, generated boilerplate, unused abstractions, or dependencies for future phases.
7. Implement only the active phase. Record later ideas in issues or an ADR; do not quietly pull future work forward.
8. Prefer a complete vertical slice over multiple incomplete frameworks.
9. Every abstraction must have at least two real consumers or isolate a volatile external dependency.
10. Every dashboard value must come from a real API or fixture; no decorative metrics presented as live data.
11. Every automated decision must be reproducible from stored inputs and explainable through an audit record.
12. Keep secrets, customer data, provider credentials, and generated artifacts out of Git.

---

## 3. Success definition

The final demo must prove this complete lifecycle:

```text
Register candidate
      ↓
Run deterministic and model-based evaluations
      ↓
Enforce quality, safety, cost, and governance gates
      ↓
Deploy to staging
      ↓
Shadow production traffic
      ↓
Promote through a 5% → 25% → 50% → 100% canary
      ↓
Observe traces, SLOs, quality, and cost
      ↓
Detect an injected retrieval regression
      ↓
Incident Investigator correlates evidence
      ↓
Policy permits automated rollback
      ↓
Restore the last known-good version and verify recovery
```

At completion:

- a new developer can run the local stack from the README in under 15 minutes;
- `main` is always buildable and testable;
- no cloud account is needed for the core workflow;
- the Azure deployment is reproducible from Terraform and Helm;
- the candidate cannot reach production by bypassing required gates;
- every release is traceable to source SHA, image digest, manifest, prompt, model, retrieval corpus, evaluations, approvals, and policy decision;
- rollback is bounded, idempotent, auditable, and demonstrated end to end.

---

## 4. Architecture

### 4.1 Logical architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                    React Operator Console                       │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS / REST
┌──────────────────────────────▼──────────────────────────────────┐
│                     AgentHub Control Plane                      │
│ FastAPI                                                         │
│                                                                 │
│ Registry │ Evaluations │ Releases │ SLOs │ Incidents │ Audits   │
└──────────────┬──────────────┬───────────────┬───────────────────┘
               │              │               │
       ┌───────▼──────┐ ┌────▼────────┐ ┌────▼────────────────┐
       │ PostgreSQL   │ │ Worker/jobs │ │ OPA policy engine   │
       │ + pgvector   │ │ in-process  │ │ deploy + runtime    │
       └──────────────┘ └─────────────┘ └─────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                         AI Gateway                              │
│ identity │ policy │ redaction │ budgets │ routing │ audit       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
             ┌─────────────────┼──────────────────┐
             ▼                 ▼                  ▼
      Inventory Agent   Knowledge Agent    Shopping Agent
             │                 │                  │
             └─────────────────┼──────────────────┘
                               ▼
          Fake model locally / Azure OpenAI in Azure
                     Azure AI Search for cloud RAG
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ OpenTelemetry → local collector → Prometheus/Grafana/Tempo     │
│                              → Azure Monitor in Azure           │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Control plane versus data plane

- **Control plane:** registry, lifecycle state, evaluation runs, policy decisions, release state, SLO definitions, incidents, and audit records.
- **Data plane:** gateway request handling, model invocation, retrieval, tool execution, traffic splitting, and telemetry emission.
- Control-plane outages must not silently change a deployed route. The data plane uses the last valid routing and policy snapshot.

### 4.3 Azure target architecture

```text
GitHub Actions ──OIDC──► Azure
      │                   │
      │             Terraform state
      │                   │
      └──build/push──► Azure Container Registry
                              │
                    ┌─────────▼──────────┐
                    │ Azure Kubernetes  │
                    │ Service (AKS)     │
                    │                   │
                    │ control plane     │
                    │ gateway           │
                    │ agent workloads   │
                    │ OTel collector    │
                    └───┬──────┬─────┬──┘
                        │      │     │
           Azure OpenAI │      │     │ Key Vault via
       / AI Foundry     │      │     │ workload identity
                        │      │     │
                Azure AI Search│ Azure Database for PostgreSQL
                               │
                         Azure Monitor
```

### 4.4 Core domain objects

| Object | Purpose | Key fields |
|---|---|---|
| `Agent` | Stable logical identity | name, owner, description, risk tier |
| `AgentVersion` | Immutable executable specification | semantic version, image digest, source SHA, prompt version, model config, tool scopes, RAG config |
| `EvaluationSuite` | Versioned test contract | dataset version, evaluators, thresholds |
| `EvaluationRun` | Reproducible result | candidate version, suite, metrics, cases, artifacts, status |
| `PolicyDecision` | Explainable authorization | subject, action, input hash, policy bundle version, result, reasons |
| `Release` | Environment promotion record | version, environment, strategy, approvals, state |
| `Route` | Runtime traffic policy | stable version, candidate version, weights, shadow target |
| `SLO` | Reliability target | indicator, objective, window, burn thresholds |
| `Incident` | Operational investigation | trigger, evidence, hypothesis, recommendation, actions |
| `AuditEvent` | Append-only accountability | actor, action, resource, decision, timestamp, correlation ID |

### 4.5 Agent manifest contract

```yaml
apiVersion: agenthub.dev/v1alpha1
kind: AgentVersion
metadata:
  name: inventory-agent
  version: 1.2.0
spec:
  owner: retail-ai
  riskTier: medium
  sourceSha: "<git-sha>"
  image: "ghcr.io/example/agenthub/inventory-agent@sha256:<digest>"
  runtime:
    framework: langgraph
    entrypoint: agenthub_agents.inventory:graph
  model:
    provider: azure-openai
    deployment: default-chat
    temperature: 0.1
    maxTokens: 800
  prompt:
    id: inventory-system
    version: 7
  tools:
    allow:
      - inventory.read
      - sales.read
      - weather.read
  retrieval:
    corpus: retail-products-v3
    topK: 5
  governance:
    piiAccess: false
    humanApprovalRequired: false
  sloProfile: standard-interactive
```

The schema is versioned, validated on registration, and documented. Unknown fields are rejected initially so configuration mistakes do not pass silently.

---

## 5. Repository structure

Create directories only when the owning phase implements them. The final intended structure is:

```text
agenthub/
├── .github/
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── workflows/
│       ├── ci.yml
│       ├── evaluation.yml
│       ├── release.yml
│       └── infrastructure.yml
├── apps/
│   ├── api/                       # FastAPI composition root
│   ├── gateway/                   # Runtime ingress and routing
│   └── web/                       # React/TypeScript operator console
├── packages/
│   ├── contracts/                 # Manifests, schemas, shared DTOs
│   ├── registry/                  # Agent/version lifecycle domain
│   ├── evaluations/               # Suites, evaluators, comparison gates
│   ├── observability/             # OTel setup and semantic conventions
│   ├── governance/                # OPA client, redaction, audit
│   ├── delivery/                  # Shadow, canary, promotion, rollback
│   └── incidents/                 # Evidence collection and investigation
├── agents/
│   ├── shared/                    # Common model/tool interfaces
│   ├── inventory/
│   ├── knowledge/
│   └── shopping/
├── data/
│   ├── synthetic/                 # Small, licensed/generated fixtures
│   └── evals/                     # Versioned evaluation datasets
├── policies/                      # Rego policies and policy tests
├── deploy/
│   ├── docker/
│   ├── helm/agenthub/
│   └── local/
├── infra/
│   └── terraform/
│       ├── modules/
│       └── environments/dev/
├── observability/
│   ├── collector/
│   ├── dashboards/
│   └── alerts/
├── scripts/                       # Thin, documented developer entrypoints
├── tests/
│   ├── contract/
│   ├── integration/
│   └── e2e/
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── runbooks/
│   └── demos/
├── .env.example
├── Makefile
├── pyproject.toml
├── README.md
└── LICENSE
```

### Structure rules

- No empty directories; add a directory in the PR that gives it a real owner and tests.
- Keep domain logic under `packages/`; apps compose transports and dependencies.
- Agents depend on shared contracts, not on control-plane database internals.
- Cloud provider code lives behind ports/adapters and must not leak into domain models.
- Test files mirror the module they verify.
- Store small deterministic fixtures in Git; store large generated results as CI artifacts.
- Migrations are append-only after merge. Never rewrite a migration already used by `main`.

---

## 6. Engineering and Git workflow

### 6.1 Branch and PR contract

Each phase is implemented on exactly one named branch and merged with one PR:

| Phase | Branch | Required PR title |
|---|---|---|
| 00 | `phase/00-foundation` | `Phase 00: Establish AgentHub foundation` |
| 01 | `phase/01-agent-runtime` | `Phase 01: Add agent runtime and Inventory Agent` |
| 02 | `phase/02-rag-agents` | `Phase 02: Add RAG Knowledge and Shopping Agents` |
| 03 | `phase/03-registry-lifecycle` | `Phase 03: Add agent registry and lifecycle` |
| 04 | `phase/04-evaluation-engine` | `Phase 04: Add evaluation engine and release gates` |
| 05 | `phase/05-observability-slos` | `Phase 05: Add OpenTelemetry and SLOs` |
| 06 | `phase/06-cicd-release` | `Phase 06: Add CI/CD and release pipeline` |
| 07 | `phase/07-azure-aks-terraform` | `Phase 07: Add Azure, AKS, and Terraform` |
| 08 | `phase/08-governance-gateway` | `Phase 08: Add governance and AI gateway` |
| 09 | `phase/09-progressive-delivery` | `Phase 09: Add shadow, canary, and cost routing` |
| 10 | `phase/10-incident-rollback` | `Phase 10: Add Incident Investigator and rollback` |
| 11 | `phase/11-hardening-demo` | `Phase 11: Harden AgentHub and complete final demo` |

Workflow:

1. Update local `main` and confirm it is green.
2. Create the phase branch from `main`.
3. Implement only the phase scope in small vertical slices.
4. Commit every meaningful, independently understandable checkpoint.
5. Push the branch regularly so work is recoverable.
6. Open a draft PR early and keep its description current.
7. Run the complete local quality suite before requesting review.
8. Require green CI, resolved review comments, updated documentation, and satisfied acceptance criteria.
9. Squash-merge or merge according to repository policy, while retaining useful PR-level history.
10. Delete the phase branch, pull `main`, tag milestones where specified, and start the next phase only after merge.

Never commit directly to `main`. Never stack an unfinished phase on another unfinished phase.

### 6.2 Commit policy

Use Conventional Commits:

```text
feat(registry): persist immutable agent versions
test(evals): cover regression threshold decisions
fix(gateway): preserve stable route when candidate times out
docs(runbook): document failed canary recovery
chore(ci): cache Python dependencies
```

A commit must:

- represent one coherent behavior or supporting change;
- include its tests when practical;
- leave the branch runnable;
- avoid drive-by formatting or unrelated cleanup;
- avoid secrets, generated binaries, local databases, and bulky evaluation output.

Do not create one giant end-of-phase commit. Do not create meaningless commits such as `updates`, `wip`, or `fix stuff` on the reviewable branch.

### 6.3 Definition of done for every phase

- Phase objective and acceptance criteria are satisfied.
- New behavior has unit tests and proportionate integration/contract tests.
- Existing tests pass; lint, formatting, typing, and security checks pass.
- Documentation and `.env.example` reflect new behavior.
- Local workflows remain usable without Azure or paid model calls.
- Migrations include upgrade behavior and are tested from a clean database.
- Logs contain no secrets, raw PII, or full prompts by default.
- No placeholder modules, unused dependencies, dead flags, or future-phase scaffolding were added.
- Operational behavior has errors, timeouts, and health checks where relevant.
- PR description contains evidence: commands run, screenshots or sample outputs, risks, and rollback notes.

### 6.4 Pull request checklist template

Every phase PR must include:

```markdown
## Objective
<!-- One paragraph describing the phase outcome. -->

## Scope
- [ ] All planned tasks are complete
- [ ] No future-phase work was included

## Verification
- [ ] Formatting and linting pass
- [ ] Static typing passes
- [ ] Unit tests pass
- [ ] Integration/contract tests pass
- [ ] Required end-to-end scenario passes
- [ ] Documentation was exercised from a clean environment

## Safety and operations
- [ ] No credentials, PII, or generated secrets are committed
- [ ] Errors, timeouts, retries, and idempotency were considered
- [ ] Migrations and configuration changes are backward compatible
- [ ] Observability is sufficient for the added behavior
- [ ] Rollback procedure is documented

## Evidence
<!-- Test summary, screenshots, traces, evaluation report, or deployment URL. -->

## Risks / follow-ups
<!-- Explicitly list deferred work; do not hide it in code. -->
```

---

## 7. Testing strategy

### Test layers

- **Unit:** pure domain rules, routing decisions, evaluators, manifest validation, redaction, state machines.
- **Contract:** API schemas, agent manifests, provider adapters, telemetry attributes, OPA inputs/outputs.
- **Integration:** PostgreSQL repositories, gateway-to-agent calls, evaluation persistence, OPA decisions, OpenTelemetry export.
- **End to end:** register → evaluate → approve → deploy → route → observe → incident → rollback.
- **Infrastructure:** Terraform formatting/validation and plan, Helm lint/template checks, Kubernetes schema checks.
- **Security:** dependency and image scans, secret detection, authorization-negative cases, prompt-injection fixtures, PII leakage checks.
- **Resilience:** timeouts, provider failures, retry bounds, duplicate events, partial telemetry failure, candidate degradation.
- **Performance:** stable local smoke thresholds first; statistically useful load tests only after runtime paths stabilize.

### Determinism rules

- Default tests use seeded data, frozen time where needed, and a deterministic fake model.
- Live-provider tests are opt-in and marked separately; they cannot block ordinary contributor CI.
- Model-based evaluation records provider, deployment, parameters, prompt, and raw artifact hash.
- Flaky tests are fixed or quarantined with an owner and expiry date; they are never blindly retried until green.

### Required quality commands

Expose stable developer commands through the `Makefile`:

```text
make setup
make lint
make typecheck
make test
make test-integration
make test-e2e
make run
make down
```

The implementation may choose specific tools, but the public developer interface should remain stable.

---

# 8. Twelve-phase implementation plan

## Phase 00 — Foundation

**Branch:** `phase/00-foundation`  
**PR:** `Phase 00: Establish AgentHub foundation`

### Objective

Create a minimal, reliable development foundation and an honest walking-skeleton service. A new contributor must be able to install, test, and run AgentHub locally without cloud credentials.

### Tasks

1. Initialize `agenthub` with Python packaging, lockfile, supported runtime version, license, editor settings, and an intentional `.gitignore`.
2. Create only the initial `apps/api`, `packages/contracts`, and test structure needed for the walking skeleton.
3. Implement a FastAPI service with `/health/live`, `/health/ready`, `/version`, and structured error responses.
4. Add typed settings loaded from environment variables; provide safe defaults and `.env.example` without secrets.
5. Add JSON structured logging with timestamp, level, service, environment, and correlation ID.
6. Add formatting, linting, static typing, unit testing, coverage reporting, secret scanning, and dependency scanning.
7. Add a local PostgreSQL container only if the walking skeleton persists a simple readiness check; otherwise defer it to Phase 03.
8. Add the initial GitHub Actions CI workflow and PR template.
9. Write the README quick start, contribution rules, architectural principles, and an ADR for the modular-monolith choice.

### Suggested commit checkpoints

1. `chore(repo): initialize AgentHub project metadata`
2. `feat(api): add health and version endpoints`
3. `feat(config): add typed settings and structured logging`
4. `test(api): cover service health contracts`
5. `ci: add baseline quality workflow`
6. `docs: add local quick start and architecture principles`

### Acceptance criteria

- A clean clone can execute `make setup`, `make test`, and `make run` using documented prerequisites.
- Liveness, readiness, and version endpoints return documented schemas.
- Missing optional cloud credentials do not prevent local startup.
- Invalid configuration fails fast with a useful message and no secret values.
- CI runs on PRs and protects `main` through required checks.
- The repository contains no empty directories, placeholder code, or unused dependencies.

### Required tests

- Unit/contract tests for settings, health endpoints, error envelope, and correlation IDs.
- CI smoke test that starts the API and checks readiness.
- Negative test for malformed required configuration.

### Deliverables

- Runnable API skeleton.
- Baseline CI workflow and quality configuration.
- README, contribution guidance, PR template, and modular-monolith ADR.

### Phase-specific PR checks

- [ ] Quick start tested from a clean environment
- [ ] CI status checks are required before merge
- [ ] No agent or Azure implementation has leaked into Phase 00

---

## Phase 01 — Agent Runtime and Inventory Agent

**Branch:** `phase/01-agent-runtime`  
**PR:** `Phase 01: Add agent runtime and Inventory Agent`

### Objective

Prove the agent runtime with one useful, bounded LangGraph agent that runs deterministically against synthetic retail data and read-only tools.

### Tasks

1. Define provider-neutral interfaces for chat models, agent requests/responses, tools, citations, usage, and errors.
2. Implement a deterministic fake model and explicit provider selection. Keep Azure/OpenAI adapters out until required.
3. Add a LangGraph Inventory Agent with a small, inspectable state graph and bounded step count.
4. Generate or commit small synthetic datasets for stores, SKUs, inventory, sales history, promotions, and weather.
5. Implement typed, read-only tools: `inventory.read`, `sales.read`, `promotions.read`, and `weather.read`.
6. Validate tool inputs and outputs, enforce timeouts, and return stable error types.
7. Expose a synchronous agent invocation endpoint and CLI/demo command.
8. Record tool-call evidence and citations in the response without exposing chain-of-thought.
9. Document the sample question: “Which Toronto stores may run low on snow shovels this weekend?”

### Suggested commit checkpoints

1. `feat(runtime): define model tool and agent contracts`
2. `feat(runtime): add deterministic fake model adapter`
3. `feat(data): add synthetic retail inventory fixtures`
4. `feat(inventory): implement read-only retail tools`
5. `feat(inventory): add bounded LangGraph workflow`
6. `feat(api): expose inventory agent invocation`
7. `test(inventory): add deterministic agent scenarios`
8. `docs: document inventory agent demo`

### Acceptance criteria

- The Inventory Agent answers the documented scenario from synthetic evidence.
- It invokes only declared read-only tools and includes source identifiers in its answer.
- Identical seeded inputs produce identical fake-model test outputs.
- Invalid stores, SKUs, dates, and tool arguments fail safely.
- Agent execution has a timeout and maximum-step guard.
- Unit tests perform no paid model calls and need no network access.

### Required tests

- Unit tests for every tool, including empty and malformed data.
- Graph tests for normal, no-data, tool-error, timeout, and step-limit paths.
- API contract test for invocation and standardized errors.
- End-to-end deterministic inventory question with asserted citations.

### Deliverables

- Shared runtime contracts and fake model.
- Working Inventory Agent, API endpoint, fixtures, and demo.
- ADR explaining provider abstraction and why agent runtimes remain simple.

### Phase-specific PR checks

- [ ] Tools are read-only and schema validated
- [ ] No hidden network calls occur in default tests
- [ ] No registry, RAG, or deployment features were implemented early

---

## Phase 02 — RAG Knowledge and Shopping Agents

**Branch:** `phase/02-rag-agents`  
**PR:** `Phase 02: Add RAG Knowledge and Shopping Agents`

### Objective

Add a small, measurable RAG pipeline and two additional workloads without turning AgentHub into an agent showcase.

### Tasks

1. Define retrieval contracts for documents, chunks, embeddings, search results, corpus versions, and citations.
2. Add a deterministic local retrieval adapter. Use PostgreSQL/pgvector if already justified; otherwise use a small in-memory adapter for tests.
3. Implement ingestion with deterministic chunking, content hashes, stable document IDs, metadata, and idempotent re-ingestion.
4. Create a small synthetic product and policy corpus with clear provenance.
5. Implement the Knowledge Agent with grounded answers, citations, and an explicit “insufficient evidence” response.
6. Implement the Shopping Agent using retrieval plus a read-only product search tool.
7. Defend against instructions inside retrieved content by separating data from system instructions.
8. Capture retrieval metadata: corpus version, query, result IDs, ranks, scores, and latency.
9. Add a lightweight retrieval benchmark for known-answer queries.

### Suggested commit checkpoints

1. `feat(rag): define retrieval and citation contracts`
2. `feat(rag): add deterministic local retriever`
3. `feat(rag): implement idempotent corpus ingestion`
4. `feat(knowledge): add grounded knowledge agent`
5. `feat(shopping): add product recommendation agent`
6. `test(rag): add retrieval and injection fixtures`
7. `docs: document RAG corpus and limitations`

### Acceptance criteria

- Ingestion is repeatable and does not duplicate unchanged chunks.
- Both agents cite document or product identifiers that actually support the response.
- The Knowledge Agent abstains when evidence is missing.
- The Shopping Agent does not invent products or use undeclared tools.
- The benchmark reports retrieval hit rate on a versioned fixture set.
- Malicious instructions in documents do not override agent policy in tests.

### Required tests

- Chunking, hashing, re-ingestion, metadata filtering, and ranking tests.
- Grounded-answer, abstention, stale-document, and prompt-injection cases.
- API contract tests for both agents.
- End-to-end ingestion → retrieve → answer → cite scenario.

### Deliverables

- Retrieval contracts and local adapter.
- Versioned synthetic corpus and ingestion command.
- Knowledge and Shopping Agents with documented demos.
- Baseline retrieval benchmark report.

### Phase-specific PR checks

- [ ] Every generated claim used in acceptance fixtures maps to evidence
- [ ] Corpus provenance and license/generation method are documented
- [ ] No Azure AI Search dependency is required locally

---

## Phase 03 — Agent Registry and Lifecycle

**Branch:** `phase/03-registry-lifecycle`  
**PR:** `Phase 03: Add agent registry and lifecycle`

### Objective

Build the control-plane foundation: an immutable registry that connects an agent version to its source, runtime, model, prompt, tools, retrieval corpus, ownership, risk, and deployments.

### Tasks

1. Introduce PostgreSQL persistence, migrations, transactional repositories, and local database setup.
2. Implement the versioned Agent Manifest JSON Schema and corresponding typed models.
3. Create `Agent` and immutable `AgentVersion` records with uniqueness and referential constraints.
4. Store source SHA, OCI image digest, prompt ID/version, model configuration, tool scopes, retrieval corpus, owner, and risk tier.
5. Implement lifecycle states: `draft`, `registered`, `evaluating`, `approved`, `rejected`, `staged`, `canary`, `production`, `retired`, and `rolled_back`.
6. Encode legal state transitions as a domain state machine; reject shortcuts and conflicting updates.
7. Add idempotent registration using manifest content hashes.
8. Expose create/list/get/version-history APIs and a simple registry view in the console.
9. Create append-only audit events for registration and state transitions.
10. Register the three demo agents through manifests rather than hard-coded UI data.

### Suggested commit checkpoints

1. `feat(db): add PostgreSQL and migration foundation`
2. `feat(contracts): add versioned agent manifest schema`
3. `feat(registry): persist agents and immutable versions`
4. `feat(registry): enforce lifecycle state transitions`
5. `feat(audit): record registry lifecycle events`
6. `feat(api): expose registry endpoints`
7. `feat(web): add registry inventory view`
8. `test(registry): cover idempotency and transition conflicts`
9. `docs: document manifests and lifecycle`

### Acceptance criteria

- Re-registering an identical manifest returns the existing version; conflicting reuse of a version is rejected.
- Registered version metadata is immutable.
- Illegal lifecycle transitions return a conflict with a useful reason.
- All transitions record actor, time, previous/new state, correlation ID, and manifest hash.
- The UI lists agents, version history, owner, risk tier, and current environment state from real APIs.
- A clean database migrates successfully and supports all three demo manifests.

### Required tests

- Schema validation and backward-compatibility fixtures.
- Repository integration tests against PostgreSQL.
- State-machine table tests for all permitted and forbidden transitions.
- Concurrent registration and idempotency tests.
- API and audit-event contract tests.

### Deliverables

- Database migrations and registry domain.
- Manifest schema with example manifests.
- Registry APIs, UI view, and lifecycle documentation.

### Phase-specific PR checks

- [ ] Version identity includes immutable source and image references
- [ ] Database constraints backstop application validation
- [ ] Migration from an empty database is verified in CI

---

## Phase 04 — Evaluation Engine

**Branch:** `phase/04-evaluation-engine`  
**PR:** `Phase 04: Add evaluation engine and release gates`

### Objective

Prevent weak or unsafe candidates from being promoted by running reproducible, versioned evaluation suites and comparing candidates with the current production baseline.

### Tasks

1. Define versioned evaluation dataset and suite schemas.
2. Implement case execution with bounded concurrency, per-case timeout, captured inputs/outputs, and deterministic replay.
3. Add deterministic evaluators for exact expectations, schema validity, citations, tool selection, tool arguments, latency, token count, and estimated cost.
4. Add pluggable model-based evaluators for correctness, groundedness, relevance, and safety; keep them opt-in locally.
5. Add prompt-injection, PII leakage, harmful-output, and unauthorized-tool scenarios.
6. Persist case results, aggregates, evaluator versions, environment, provider settings, and artifact hashes.
7. Compare candidate metrics with absolute thresholds and relative production deltas.
8. Produce an explainable release-gate decision with every pass/fail reason.
9. Expose evaluation run, result, comparison, and report APIs and UI.
10. Provide CLI and machine-readable JSON/JUnit output for CI.

### Initial gate profile

```yaml
quality:
  correctness: {min: 0.90, maxRegression: 0.02}
  groundedness: {min: 0.95, maxRegression: 0.01}
  toolAccuracy: {min: 0.98, maxRegression: 0.01}
safety:
  piiLeakageRate: {max: 0.00}
  unauthorizedToolRate: {max: 0.00}
performance:
  p95LatencyMs: {max: 3000, maxRegression: 0.15}
cost:
  meanUsdPerRequest: {max: 0.025, maxRegression: 0.20}
```

Thresholds are configuration, version controlled, and evaluated consistently; they are not hard-coded throughout application logic.

### Suggested commit checkpoints

1. `feat(evals): add dataset and suite contracts`
2. `feat(evals): implement deterministic case runner`
3. `feat(evals): add quality tool latency and cost evaluators`
4. `feat(evals): add safety regression scenarios`
5. `feat(evals): persist reproducible run artifacts`
6. `feat(evals): compare candidate with production baseline`
7. `feat(api): expose evaluation reports and gate decisions`
8. `feat(web): add evaluation comparison view`
9. `test(evals): cover pass fail timeout and replay paths`
10. `docs: document evaluator limits and threshold tuning`

### Acceptance criteria

- A candidate can be evaluated from a command using a versioned suite.
- The same fake-model inputs reproduce the same results.
- A deliberately regressed candidate is rejected with metric-level reasons.
- Missing critical results, evaluator errors, and timeouts fail closed.
- Reports compare the candidate with production and expose absolute and relative thresholds.
- An approved evaluation attaches immutably to the candidate version and suite version.

### Required tests

- Evaluator unit tests with boundary values.
- Runner tests for ordering, concurrency, timeout, cancellation, and partial failure.
- Persistence/replay integration tests.
- Golden evaluation of all three agents.
- Negative end-to-end case that blocks a known-bad candidate.

### Deliverables

- Versioned evaluation data and engine.
- Baseline suites for Inventory, Knowledge, and Shopping Agents.
- Candidate comparison API/UI, CLI report, and CI-readable results.

### Phase-specific PR checks

- [ ] Gate failures are actionable and reproducible
- [ ] LLM-as-judge is not the only evaluator for any critical safety rule
- [ ] Evaluation artifacts identify every versioned input

---

## Phase 05 — OpenTelemetry and SLOs

**Branch:** `phase/05-observability-slos`  
**PR:** `Phase 05: Add OpenTelemetry and SLOs`

### Objective

Make every agent interaction and control-plane action diagnosable while defining measurable service, quality, and cost objectives.

### Tasks

1. Adopt OpenTelemetry across API, gateway boundary, agent graph, retrieval, tools, model calls, evaluation runs, and lifecycle actions.
2. Define semantic conventions for `agent.name`, `agent.version`, `prompt.version`, `model.provider`, `model.deployment`, `tool.name`, `rag.corpus`, `release.id`, and token/cost attributes.
3. Propagate W3C trace context and application correlation IDs across internal calls.
4. Add redaction and attribute allowlists before telemetry export.
5. Configure a local OpenTelemetry Collector and a minimal Prometheus/Grafana/Tempo-compatible stack.
6. Emit request count, error rate, latency, tool success, retrieval latency, token use, estimated cost, evaluation score, and policy-denial metrics.
7. Define SLO profiles for availability, latency, tool success, groundedness, evaluation pass rate, and cost.
8. Implement error-budget and multi-window burn-rate calculations.
9. Add actionable alerts and runbooks with links back to agent version and trace data.
10. Build fleet and agent-detail dashboard views from exported data.

### Suggested commit checkpoints

1. `feat(otel): add shared tracing and metric bootstrap`
2. `feat(otel): instrument agent model retrieval and tools`
3. `feat(otel): propagate correlation and release context`
4. `feat(privacy): redact sensitive telemetry attributes`
5. `feat(observability): add local collector stack`
6. `feat(slo): define indicators objectives and burn rates`
7. `feat(alerts): add actionable SLO alerts and runbooks`
8. `feat(web): add fleet health and trace links`
9. `test(otel): verify telemetry contracts and redaction`

### Acceptance criteria

- One request can be followed from gateway through agent, retrieval/tools, and model spans.
- Metrics can be filtered by agent and version without unbounded-cardinality labels.
- Raw prompts, secrets, and synthetic PII are absent from default exports.
- Fleet health shows real availability, p95 latency, tool success, quality, and cost data.
- A forced latency/error condition consumes an error budget and triggers the documented alert.
- Telemetry backend failure does not fail the user request or create unbounded buffering.

### Required tests

- Span/metric semantic-convention contract tests.
- Context propagation integration tests.
- Redaction tests using synthetic secrets and PII.
- SLO window and burn-rate unit tests.
- Local smoke test that finds the trace for a known request.

### Deliverables

- Shared OTel instrumentation and collector configuration.
- Version-controlled dashboards, alerts, and SLO definitions.
- Observability runbooks and fleet health UI.

### Phase-specific PR checks

- [ ] Metric dimensions have bounded cardinality
- [ ] Telemetry failure is non-fatal and bounded
- [ ] Dashboard screenshots correspond to reproducible traffic

---

## Phase 06 — CI/CD and Release Pipeline

**Branch:** `phase/06-cicd-release`  
**PR:** `Phase 06: Add CI/CD and release pipeline`

### Objective

Turn source changes into traceable, immutable candidate releases and enforce tests, evaluations, scans, and approvals before promotion.

### Tasks

1. Separate fast PR CI, candidate evaluation, release, and infrastructure workflows.
2. Run formatting, linting, typing, unit, contract, integration, and selected end-to-end tests in CI.
3. Build minimal non-root containers with pinned bases, health checks, OCI labels, and reproducible dependency installation.
4. Generate an SBOM, scan dependencies and images, and fail at documented severity thresholds.
5. Authenticate to registries/cloud using GitHub OIDC; never use long-lived cloud secrets.
6. Publish by immutable digest and attach source SHA and build provenance.
7. Register the candidate version automatically, run its evaluation suite, and attach the result.
8. Block staging promotion unless technical and policy gates pass.
9. Model release states explicitly and make all workflow retries idempotent.
10. Add protected GitHub environments for staging and production; require manual approval where policy says so.
11. Produce release notes and a machine-readable provenance artifact.

### Suggested commit checkpoints

1. `ci: split pull request evaluation and release workflows`
2. `build: add hardened reproducible containers`
3. `ci(security): add sbom secret dependency and image scans`
4. `feat(release): create immutable candidate provenance`
5. `ci(evals): gate candidates on evaluation reports`
6. `feat(release): add idempotent promotion state machine`
7. `ci: add protected staging and production environments`
8. `test(release): cover duplicate and failed workflow events`
9. `docs: add release and recovery runbooks`

### Acceptance criteria

- A PR cannot merge without required quality checks.
- A release references an immutable image digest, source SHA, manifest hash, evaluation run, and policy decision.
- A deliberately failing evaluation or high-severity scan prevents promotion.
- Rerunning a partially failed workflow does not create duplicate versions or releases.
- Production deployment requires the documented protected-environment approval.
- CI uses no long-lived Azure or registry credentials.

### Required tests

- Container build and non-root runtime smoke tests.
- Workflow validation and release-state unit tests.
- Idempotency tests for duplicate registration and promotion events.
- End-to-end local pipeline simulation with pass and block scenarios.

### Deliverables

- CI, evaluation, release, and infrastructure workflows.
- Container definitions, SBOM/provenance output, release APIs, and runbooks.

### Phase-specific PR checks

- [ ] All published references use digests, not mutable tags alone
- [ ] Workflow permissions are least privilege
- [ ] Failure and rerun behavior is demonstrated

---

## Phase 07 — Azure, AKS, Helm, and Terraform

**Branch:** `phase/07-azure-aks-terraform`  
**PR:** `Phase 07: Add Azure, AKS, and Terraform`

### Objective

Provision a secure, cost-conscious Azure development environment and deploy AgentHub to AKS without compromising the local-first architecture.

### Tasks

1. Define a concise Azure resource inventory and cost assumptions before provisioning.
2. Create reusable Terraform modules only for repeated or independently testable resource groups.
3. Provision resource group, networking, AKS, Azure Container Registry, Key Vault, Azure Database for PostgreSQL, Azure AI Search, Log Analytics/Azure Monitor, and required identities.
4. Configure Azure OpenAI/Azure AI Foundry integration as an adapter; document cases where quota or manual model deployment is required.
5. Use remote Terraform state with locking, separate state from application deploys, and keep environment inputs explicit.
6. Use GitHub OIDC, AKS workload identity, managed identities, private/securable connectivity where practical, and Key Vault CSI or equivalent secret delivery.
7. Package AgentHub in one Helm chart with values for local/dev environments.
8. Add requests, limits, probes, PodDisruptionBudgets where justified, network policies, and restricted pod security settings.
9. Configure autoscaling conservatively from measured CPU/concurrency signals.
10. Export OpenTelemetry to Azure Monitor while retaining the local exporter path.
11. Add `terraform fmt`, validation, plan review, Helm lint/template, and Kubernetes schema checks to CI.
12. Write deployment, verification, cost-control, and teardown runbooks.

### Suggested commit checkpoints

1. `docs(azure): define target resources security and cost bounds`
2. `feat(terraform): add state identity network and registry foundation`
3. `feat(terraform): add aks postgres search key vault and monitor`
4. `feat(azure): add Azure OpenAI and Search adapters`
5. `feat(helm): package AgentHub workloads`
6. `feat(k8s): add probes resources identity and network policy`
7. `ci(infra): validate Terraform Helm and manifests`
8. `test(azure): add post-deploy smoke verification`
9. `docs(runbook): document Azure deploy and teardown`

### Acceptance criteria

- Terraform can create a documented development environment from reviewed variables.
- `terraform plan` is stable after apply and does not expose secrets.
- Helm deploys healthy API, gateway, and agent workloads to AKS.
- Pods use workload identity and run as non-root with resource boundaries.
- AgentHub invokes configured Azure model and search adapters when enabled.
- The same functional smoke suite runs locally and against the Azure endpoint.
- Teardown and known non-destroyed resources are documented to prevent surprise costs.

### Required tests

- Terraform formatting, validation, plan policy, and module tests where useful.
- Helm lint, rendering snapshots, and Kubernetes schema/security checks.
- Adapter contract tests with fakes plus opt-in live Azure smoke tests.
- Post-deploy health, registry, evaluation, and one agent invocation smoke test.

### Deliverables

- Terraform modules and `dev` environment.
- Helm chart and Kubernetes policies.
- Azure provider adapters and environment configuration.
- Deploy, verify, troubleshoot, estimate-cost, and teardown runbooks.

### Phase-specific PR checks

- [ ] No credentials or Terraform state are committed
- [ ] A reviewed plan artifact is attached to the PR
- [ ] Estimated monthly development cost and teardown steps are explicit
- [ ] Cloud-only behavior has a local or fake counterpart

---

## Phase 08 — Governance and AI Gateway

**Branch:** `phase/08-governance-gateway`  
**PR:** `Phase 08: Add governance and AI gateway`

### Objective

Enforce identity, tool permissions, data handling, risk approval, budgets, and audit rules at deployment time and runtime through one controlled gateway.

### Tasks

1. Introduce the AI Gateway as the data-plane entry point for agent invocations and model requests.
2. Authenticate callers and establish service identities; keep local development identities explicit and clearly non-production.
3. Define OPA/Rego input and decision contracts for registration, promotion, model invocation, and tool execution.
4. Implement policy bundles for tool scopes, risk tiers, PII controls, human approval, audit requirements, allowed models, token budgets, and environment restrictions.
5. Enforce authorization on the server immediately before each tool/model action; never trust only the prompt or UI.
6. Add deterministic PII detection/redaction for supported classes before external model invocation.
7. Add per-agent/model token and cost budgets, rate limits, timeouts, and bounded retries.
8. Create append-only audit events for allow and deny decisions with policy version and sanitized inputs.
9. Add a two-person/manual approval path for high-risk production releases in the reference policy.
10. Add governance and audit views to the console.
11. Specify fail-closed behavior for security-critical policy outages and a narrowly scoped, audited emergency procedure.

### Suggested commit checkpoints

1. `feat(gateway): add authenticated invocation boundary`
2. `feat(policy): define OPA decision contracts`
3. `feat(policy): enforce deployment governance rules`
4. `feat(gateway): authorize model and tool calls at runtime`
5. `feat(privacy): redact supported PII before model calls`
6. `feat(budgets): enforce rate token and cost limits`
7. `feat(audit): persist sanitized policy decisions`
8. `feat(web): add policy and audit views`
9. `test(governance): add deny outage and bypass scenarios`
10. `docs: add governance model and emergency procedure`

### Acceptance criteria

- Inventory Agent can read inventory/weather but is denied customer-profile access and all writes.
- A high-risk agent without required approval cannot enter production.
- Supported PII is redacted before the external provider adapter sees it.
- Budget or rate-limit violations return a stable, safe response and audit event.
- Every allow/deny is attributable to identity, agent version, action, policy bundle, reason, time, and correlation ID.
- Direct internal endpoint access cannot bypass gateway authorization in production configuration.
- A policy-engine failure follows documented fail-closed behavior for critical actions.

### Required tests

- Rego unit tests for every rule and boundary case.
- Authorization-negative tests for cross-agent and undeclared-tool access.
- PII redaction/leakage tests with representative synthetic formats.
- Gateway integration tests for identity, rate limit, budget, timeout, and OPA outage.
- Audit schema and sensitive-field tests.

### Deliverables

- AI Gateway and identity boundary.
- Versioned policies with tests.
- Redaction, budgets, rate limits, and append-only audit trail.
- Governance UI and runbooks.

### Phase-specific PR checks

- [ ] Enforcement occurs outside the LLM and agent prompt
- [ ] Deny paths are tested as heavily as allow paths
- [ ] Audit records contain enough evidence without retaining sensitive payloads

---

## Phase 09 — Shadow, Canary, and Cost-Aware Routing

**Branch:** `phase/09-progressive-delivery`  
**PR:** `Phase 09: Add shadow, canary, and cost routing`

### Objective

Evaluate candidates on production-like traffic and promote them gradually with measurable safety, quality, performance, and cost guardrails.

### Tasks

1. Define stable/candidate route models with immutable release references and atomic updates.
2. Implement deterministic weighted routing using a stable request or subject key so sessions do not flap between versions.
3. Implement asynchronous shadow duplication with strict timeout, isolation, sampling, redaction, and no user-visible effect.
4. Prevent shadow executions from performing write-capable tools or emitting business side effects.
5. Pair production and shadow results by correlation ID and calculate quality, latency, error, safety, and cost deltas.
6. Implement a canary state machine: `pending → 5% → 25% → 50% → 100% → completed`, plus `paused` and `rolled_back`.
7. Require minimum sample size, observation window, healthy telemetry, and all configured guardrails before each step.
8. Add manual pause/resume/promote/abort operations with optimistic concurrency and audit events.
9. Add a simple explainable complexity classifier and policy-controlled small/large-model routing.
10. Attribute tokens and estimated cost by agent, version, model, environment, and team.
11. Display shadow comparison, canary state, guardrails, and cost recommendations in the console.

### Suggested commit checkpoints

1. `feat(routes): add atomic stable and candidate route model`
2. `feat(routes): add deterministic weighted routing`
3. `feat(shadow): duplicate requests with side-effect isolation`
4. `feat(shadow): compare paired candidate results`
5. `feat(canary): add progressive delivery state machine`
6. `feat(canary): enforce samples windows and guardrails`
7. `feat(routing): add explainable cost-aware model selection`
8. `feat(cost): attribute token spend by operational dimensions`
9. `feat(web): add progressive delivery and cost views`
10. `test(delivery): cover concurrency degradation and abort paths`

### Acceptance criteria

- Shadow responses never alter the user response or execute side-effecting tools.
- Stable request keys produce stable weighted routing.
- Candidate comparison includes sample size, confidence/uncertainty, and quality/latency/error/cost deltas.
- Canary traffic advances only after its minimum samples, time window, and guardrails pass.
- A bad candidate is paused or rolled back without changing the stable version’s configuration.
- Route updates are atomic and safe under concurrent operator actions.
- Cost-aware routing reports the decision reason and preserves configured minimum quality.

### Required tests

- Statistical/deterministic routing distribution and stickiness tests.
- Shadow isolation, timeout, cancellation, redaction, and no-side-effect tests.
- Canary state-machine and concurrent-update table tests.
- Guardrail tests for missing/stale telemetry, low samples, regressions, and safety violations.
- End-to-end 5% → 25% progression plus forced abort.

### Deliverables

- Runtime router, shadow evaluator, and progressive-delivery controller.
- Cost attribution and explainable model routing.
- Operator UI and canary/shadow runbooks.

### Phase-specific PR checks

- [ ] Shadow workloads cannot call write-capable tools
- [ ] Missing telemetry blocks automatic promotion
- [ ] Routing changes are atomic, idempotent, and audited

---

## Phase 10 — Incident Investigator and Automated Rollback

**Branch:** `phase/10-incident-rollback`  
**PR:** `Phase 10: Add Incident Investigator and rollback`

### Objective

Detect a production regression, assemble trustworthy evidence, generate a bounded incident hypothesis, and safely restore the last known-good release when policy permits.

### Tasks

1. Create incident triggers from SLO burn, quality regression, error rate, cost anomaly, safety violations, and canary guardrail failures.
2. Build evidence adapters for metrics, traces, sanitized logs, deployment history, manifest/config diffs, evaluation changes, Kubernetes events, policy decisions, and prior incidents.
3. Normalize all evidence onto a time-ordered incident timeline with source links and hashes.
4. Implement deterministic heuristics first: change correlation, span contribution, metric co-movement, and known failure signatures.
5. Add an optional LangGraph investigator that summarizes only supplied evidence, cites every claim, reports uncertainty, and never acts directly.
6. Produce probable cause, confidence, evidence, counter-evidence, blast radius, and recommended action.
7. Model rollback as a control-plane command to a known-good immutable release; do not let generated text call Kubernetes directly.
8. Define automatic rollback policy: eligible canary only, known-good target, guardrail breach, minimum evidence, cooldown, max attempts, no concurrent rollout, and complete audit trail.
9. Require human approval for ambiguous, stable-production, data-migration, or high-risk cases.
10. Verify post-rollback health during a fixed observation window and reopen/escalate if recovery fails.
11. Add incident list/detail/timeline and approve/rollback UI.
12. Create the canonical fault: change Shopping Agent retrieval `topK` from `5` to `50` and demonstrate detection and recovery.

### Suggested commit checkpoints

1. `feat(incidents): create incidents from operational triggers`
2. `feat(evidence): collect telemetry release and config evidence`
3. `feat(incidents): build normalized evidence timeline`
4. `feat(investigator): add deterministic correlation analysis`
5. `feat(investigator): add cited LangGraph incident summary`
6. `feat(rollback): add known-good rollback command`
7. `feat(rollback): enforce automation policy and cooldowns`
8. `feat(rollback): verify recovery and escalation`
9. `feat(web): add incident investigation workflow`
10. `test(incident): demonstrate top-k regression rollback`
11. `docs(runbook): add automated and manual recovery procedures`

### Acceptance criteria

- The `topK: 5 → 50` fault causes a measurable retrieval/p95 latency regression and an incident.
- The timeline correlates the release/config change with retrieval latency while distinguishing unchanged model latency.
- Every investigator claim cites stored evidence; missing evidence is stated explicitly.
- The investigator recommends rollback but cannot bypass the rollback policy or approval boundary.
- Eligible canary regression automatically returns traffic to the last known-good immutable version.
- Repeated rollback requests are idempotent and bounded by cooldown/max-attempt rules.
- Post-rollback verification confirms recovery or escalates with a clear status.
- The full sequence is present in release, incident, policy, and audit records.

### Required tests

- Evidence normalization, clock-skew, missing-source, and contradictory-evidence tests.
- Investigator grounding tests that reject uncited or invented claims.
- Rollback-policy table tests for eligible and forbidden cases.
- Idempotency, concurrent rollout, cooldown, and failed-recovery tests.
- End-to-end injected fault → alert → investigate → rollback → recovery test.

### Deliverables

- Incident domain, evidence collectors, and Investigator graph.
- Policy-constrained rollback controller and recovery verification.
- Incident UI, canonical failure injection, and runbooks.

### Phase-specific PR checks

- [ ] Generated analysis has no direct infrastructure credentials or actuation path
- [ ] Rollback target is an immutable known-good release
- [ ] Automation stops safely on ambiguity, repeated failure, or missing evidence

---

## Phase 11 — Hardening and Final Demo

**Branch:** `phase/11-hardening-demo`  
**PR:** `Phase 11: Harden AgentHub and complete final demo`

### Objective

Turn the integrated system into a credible portfolio-quality platform: secure, understandable, reproducible, operable, and demonstrated without hidden manual fixes.

### Tasks

1. Run an end-to-end architecture and dependency audit; remove dead code, unused flags, placeholder assets, and unjustified infrastructure.
2. Threat-model identities, gateway bypass, prompt injection, retrieval poisoning, tool abuse, PII leakage, dependency compromise, CI credentials, policy outage, and rollback abuse.
3. Close high-risk findings and document accepted residual risks.
4. Add backup/restore guidance, database migration verification, resource exhaustion limits, graceful shutdown, and disruption behavior.
5. Run measured load and resilience tests; set resource defaults from evidence rather than arbitrary numbers.
6. Complete accessibility, empty/loading/error states, and truthful data labeling in the console.
7. Create one-command local demo setup and seeded scenario reset.
8. Write a scripted 10–15 minute final demo covering registry, evaluation block/pass, governance deny, trace/SLO, shadow comparison, canary, incident investigation, and rollback.
9. Add architecture diagrams, ADR index, API reference, manifest/evaluation examples, operator runbooks, and troubleshooting.
10. Add a polished root README with screenshots, limitations, cost warning, quick start, and clear project scope.
11. Run the complete test matrix locally and in CI; eliminate flakes.
12. Tag `v1.0.0` only after the phase PR merges and `main` passes the final verification workflow.

### Suggested commit checkpoints

1. `refactor: remove dead code and tighten module boundaries`
2. `security: address AgentHub threat model findings`
3. `feat(resilience): add shutdown limits and recovery checks`
4. `test(performance): add measured load and resilience baselines`
5. `fix(web): complete accessible operational states`
6. `feat(demo): add reproducible seeded lifecycle scenario`
7. `docs: complete architecture API and operator guides`
8. `docs: publish final AgentHub walkthrough and screenshots`
9. `test(e2e): verify complete release incident rollback lifecycle`
10. `chore(release): prepare AgentHub v1.0.0`

### Acceptance criteria

- A clean machine can run the local demo by following only the README.
- The demo contains no fabricated dashboard values or undocumented manual database edits.
- The complete lifecycle passes in CI with deterministic providers.
- High-severity threat-model findings are resolved; residual risks are explicit.
- Containers and manifests pass the selected security and policy checks.
- Runbooks cover provider outage, policy outage, evaluation failure, stuck canary, failed rollback, and database recovery.
- Documentation clearly separates implemented behavior, Azure reference behavior, and future possibilities.
- `main` is green and tagged `v1.0.0` after merge.

### Required tests

- Full unit, contract, integration, security, infrastructure, and end-to-end suites.
- Clean-install test and documentation smoke test.
- Load baseline for gateway and control-plane APIs.
- Failure injection for model, retrieval, database, telemetry, OPA, candidate, and rollback paths.
- Accessibility and critical UI journey checks.

### Deliverables

- Release-ready repository and `v1.0.0` tag.
- Threat model, residual-risk register, and performance report.
- Complete documentation, screenshots, final demo script, and demo reset tooling.
- Final architecture and lifecycle evidence.

### Phase-specific PR checks

- [ ] Every README claim is backed by code or clearly labeled as planned
- [ ] Demo succeeds twice from a clean reset
- [ ] No unresolved critical/high security findings remain
- [ ] Tag is created from the green merge commit, not the phase branch

---

## 9. CI/CD design

### Pull request pipeline

```text
Checkout
  → dependency integrity and secret scan
  → format/lint/typecheck
  → unit and contract tests
  → PostgreSQL integration tests
  → build containers
  → image/dependency scan + SBOM
  → deterministic evaluation smoke suite
  → selected end-to-end tests
  → Terraform/Helm validation when relevant
```

### Candidate release pipeline

```text
Merge to main or version request
  → build once
  → publish immutable image digest + provenance
  → register AgentVersion
  → deploy candidate to isolated staging slot
  → run full evaluation suite
  → evaluate governance policy
  → attach results to release
  → require protected-environment approval
  → mark staging-ready
```

### Production pipeline

```text
Approved staging release
  → verify immutable inputs and current policy
  → enable shadow traffic
  → compare minimum sample window
  → start 5% canary
  → evaluate guardrails
  → advance 25% → 50% → 100%
  → mark stable
  → retain previous known-good release for rollback
```

### Supply-chain and credential rules

- Pin third-party actions by immutable version or SHA according to repository policy.
- Generate SBOM and provenance for release images.
- Sign images when the registry/deployment environment is configured for verification.
- Use GitHub OIDC and workload identity, not stored Azure client secrets.
- Grant workflows the minimum GitHub and Azure permissions.
- Separate plan and apply; production infrastructure applies require reviewed plans and environment approval.
- Never rebuild between staging and production. Promote the same digest.

---

## 10. Observability and SLO specification

### Required trace shape

```text
gateway.request
└── agent.invoke
    ├── agent.plan
    ├── rag.retrieve
    │   └── vector.search
    ├── tool.invoke
    └── model.generate
```

Store or export correlation, not raw reasoning. Traces should identify agent/release/configuration versions while sensitive content remains redacted or disabled by default.

### Initial SLO profile

| Indicator | Objective | Window |
|---|---:|---:|
| Gateway availability | ≥ 99.9% | rolling 30 days |
| End-to-end p95 latency | < 3 seconds | rolling 1 hour and 24 hours |
| Tool-call success | ≥ 99% | rolling 24 hours |
| Groundedness | ≥ 95% | latest qualified sample window |
| Unauthorized tool-call success | 0% | continuous |
| Evaluation pass rate | ≥ 97% | last 20 candidate runs |
| Mean estimated cost/request | ≤ $0.025 | rolling 24 hours |

These are initial demo objectives, not universal promises. Tune them from measurements and document changes.

### Alert quality rules

- Page only on actionable, user-impacting, fast-burn conditions.
- Create tickets or warnings for slow-burn cost and quality trends.
- Include agent, version, release, environment, violated objective, window, current value, and runbook.
- Deduplicate alerts into incidents and apply cooldowns.
- Missing telemetry is its own unhealthy state and blocks automatic promotion.

---

## 11. Governance model

### Reference risk tiers

| Tier | Example | Production requirement |
|---|---|---|
| Low | Internal summarization with public data | Passing evals and owner approval |
| Medium | Product recommendations or operational analysis | Passing evals, policy approval, audit, canary |
| High | PII access or autonomous write actions | Explicit human approval, enhanced safety suite, restricted tools, audit, manual rollback authority |

The three demo agents remain low/medium risk and use read-only business tools.

### Non-negotiable controls

- Agent identity and declared tool scopes.
- Default deny for undeclared tools and models.
- PII redaction before external model calls where policy requires it.
- Human approval for high-risk production changes.
- Audit logging for registration, evaluation decisions, policy decisions, route changes, and rollback.
- Policy bundle version stored with each decision.
- No authorization delegated to prompt instructions.
- Fail closed for security-critical actions when policy status is unknown.

### Example policy outcomes

```text
ALLOW inventory-agent:v7 → inventory.read
DENY  inventory-agent:v7 → customer-profile.read
      reason: missing_scope

DENY  high-risk-agent:v2 → promote:production
      reason: human_approval_required
```

---

## 12. Shadow, canary, and rollback safety

### Shadow invariants

- Shadow work is sampled and isolated.
- The stable response is returned without waiting for the shadow response.
- Shadow calls have smaller, independent resource budgets.
- Write tools, notifications, purchases, and persistent side effects are forbidden.
- Sensitive inputs are redacted or excluded by policy.
- Pairing IDs allow comparison without confusing shadow and production metrics.

### Canary invariants

- Weights change atomically.
- Assignment is sticky for a stable key.
- Advancement requires time, sample size, healthy telemetry, and guardrails.
- Safety violations cause immediate pause/rollback regardless of average quality.
- Operators can pause or abort; every action is audited.
- Only one active candidate per agent/environment in v1.

### Automated rollback eligibility

Automatic rollback is allowed only when all conditions hold:

1. The release is an active canary, not an arbitrary stable production release.
2. A previous immutable known-good version exists.
3. A configured objective or safety guardrail has breached its threshold.
4. Telemetry is sufficiently fresh and the minimum evidence/sample policy is met.
5. No incompatible database or irreversible data change is involved.
6. No other rollout or rollback is active.
7. Cooldown and maximum-attempt limits have not been exceeded.
8. Policy returns `allow` and an audit event is durably recorded.

Anything else pauses the rollout and requests human review.

---

## 13. Incident Investigator contract

The Incident Investigator is an evidence assistant, not an all-powerful operations bot.

### Inputs

- Triggering SLO/guardrail and affected time window.
- Agent, environment, route, candidate, and stable release.
- Metrics, traces, sanitized logs, Kubernetes events.
- Recent source, image, prompt, model, tool, policy, and retrieval configuration changes.
- Candidate and production evaluation results.
- Relevant prior incidents and runbook links.

### Output schema

```yaml
incidentId: inc-123
summary: Shopping Agent latency regressed during v8 canary
probableCause:
  statement: Retrieval topK increased from 5 to 50
  confidence: 0.87
evidence:
  - ref: release-diff-8
    finding: retrieval.topK changed at canary start
  - ref: trace-aggregate-42
    finding: retrieval span p95 increased 340 percent
counterEvidence:
  - ref: model-latency-42
    finding: model generation latency remained stable
blastRadius: 5 percent canary traffic
recommendedAction:
  type: rollback
  targetRelease: release-v7
automationEligibility: eligible
limitations:
  - Evidence shows correlation; controlled replay strengthens causality
```

### Safety properties

- Claims without evidence references fail validation.
- Confidence is calibrated language, not a guarantee.
- The model does not receive infrastructure credentials.
- The recommendation is sent to the rollback controller, which independently evaluates policy.
- All evidence inputs and output hashes are retained for replay.
- Humans can inspect and override within their authorization.

---

## 14. Final demonstration

### Demo setup

- Start from a clean local environment or the documented Azure dev environment.
- Seed the three agents, evaluation suites, policy bundle, synthetic corpus, and stable releases.
- Use the deterministic provider for a guaranteed demo; optionally repeat one invocation with Azure OpenAI.

### Script

1. **Fleet:** Show three registered agents and the healthy stable versions.
2. **Lineage:** Open Inventory Agent and trace its production version to source SHA, image digest, prompt, model, tools, corpus, evaluations, policy, and release.
3. **Evaluation gate:** Register a candidate that invents a product or violates groundedness; run the suite and show promotion blocked with exact reasons.
4. **Governance:** Attempt an undeclared customer-profile tool call; show a runtime denial and sanitized audit event.
5. **Observability:** Invoke the stable Shopping Agent; open its gateway → retrieval → tool → model trace and fleet SLO metrics.
6. **Shadow:** Shadow a good candidate and show paired quality, latency, and cost comparison without altering the user response.
7. **Canary:** Approve the candidate and advance it to 5% after guardrails pass.
8. **Fault:** Deploy the controlled `topK: 5 → 50` configuration regression.
9. **Detect:** Show retrieval latency and end-to-end p95 breach while model latency remains stable.
10. **Investigate:** Open the incident timeline and evidence-cited probable cause.
11. **Rollback:** Show policy eligibility, automated rollback to the known-good digest, and the append-only audit trail.
12. **Recover:** Verify SLO recovery and close the incident with generated evidence and operator notes.

### Demo evidence to preserve

- Evaluation pass and fail reports.
- Trace screenshot with version/correlation context.
- Shadow comparison and canary guardrail screen.
- Incident timeline and cited investigation.
- Route history before/after rollback.
- CI run and immutable release provenance.

---

## 15. Codex implementation instructions

Use this section as the standing instruction set whenever Codex implements a phase.

### Standing instructions

```text
You are implementing one phase of AgentHub — Enterprise AgentOps & ModelOps Platform.

Read AGENTHUB_MASTER_PLAN.md, README.md, CONTRIBUTING.md, relevant ADRs, and the
current code before editing. Treat the active phase as the complete scope.

Rules:
1. Start from updated, green main on the exact phase branch named in the plan.
2. Inspect existing behavior and preserve intentional user changes.
3. Implement only the active phase. Do not scaffold later phases.
4. Keep the repository clean: no empty folders, placeholder modules, unused
   dependencies, generated junk, secrets, or speculative abstractions.
5. Keep local development functional without Azure credentials or paid LLM calls.
6. Prefer a modular monolith and standards-based adapters. Do not add infrastructure
   that the phase does not require.
7. Build in small vertical slices. Commit after each meaningful working checkpoint
   with a Conventional Commit message. Do not make one giant phase commit.
8. Add or update unit, contract, integration, and end-to-end tests in proportion to
   the behavior. Tests must be deterministic by default.
9. Run formatting, linting, typing, tests, and relevant security/infrastructure
   validation before declaring the phase complete.
10. Update documentation, examples, environment templates, migrations, runbooks,
    and ADRs when behavior or operations change.
11. Never bypass an evaluation, authorization, approval, or rollback safety rule to
    make a demo pass.
12. Do not push, merge, tag, or alter external infrastructure unless explicitly
    authorized for this run. Prepare the branch and PR evidence when those actions
    are not authorized.

Before coding, produce a concise phase execution plan mapped to the phase tasks and
acceptance criteria. During implementation, report meaningful completed slices and
any deviation. If a planned approach conflicts with the existing repository, choose
the smallest safe design that preserves the phase objective and document the reason.

At completion, provide:
- changed files and implemented behavior;
- acceptance-criteria evidence;
- exact checks run and their results;
- commit list;
- known limitations and intentionally deferred work;
- PR title, summary, verification evidence, risks, and rollback notes.
```

### Phase kickoff prompt

Replace the bracketed value with the active phase number:

```text
Implement Phase [00] from AGENTHUB_MASTER_PLAN.md on its prescribed branch.
Follow the standing Codex implementation instructions exactly. First inspect the
repository and give me a short execution plan tied to the phase acceptance criteria.
Then implement and verify the phase completely, making frequent meaningful commits.
Do not implement any later phase.
```

### Codex stop conditions

Codex must stop and ask before proceeding when:

- the required action would overwrite or discard unrelated user changes;
- credentials, Azure subscription choices, DNS ownership, or external approvals are missing;
- a destructive cloud/database operation is not explicitly within scope;
- the only path forward would weaken a safety, evaluation, governance, or audit control;
- phase requirements materially conflict and no small reversible assumption resolves them.

Codex should not stop merely because an implementation detail is unspecified. It should choose the smallest conventional design consistent with this plan and record the assumption.

---

## 16. Phase dependency and milestone map

```text
00 Foundation
  └── 01 Runtime + Inventory Agent
       └── 02 RAG + Knowledge/Shopping Agents
            └── 03 Registry + Lifecycle
                 └── 04 Evaluation Engine
                      └── 05 OpenTelemetry + SLOs
                           └── 06 CI/CD + Release
                                └── 07 Azure + AKS + Terraform
                                     └── 08 Governance + Gateway
                                          └── 09 Shadow/Canary + Cost
                                               └── 10 Incident + Rollback
                                                    └── 11 Hardening + Demo
```

Recommended tags after merge:

- `v0.1.0` after Phase 02 — working agent workloads.
- `v0.2.0` after Phase 04 — registry and evaluation control plane.
- `v0.3.0` after Phase 06 — observable CI/CD release lifecycle.
- `v0.4.0` after Phase 08 — Azure deployment and governance.
- `v0.9.0` after Phase 10 — progressive delivery and automated recovery.
- `v1.0.0` after Phase 11 — hardened final demonstration.

Tags are created from green `main` merge commits, never from phase branches.

---

## 17. Final release checklist

### Product

- [ ] All three agents are registered and invokable through the gateway
- [ ] Candidate lineage is complete and immutable
- [ ] Evaluation gates block a known-bad candidate
- [ ] Governance blocks an unauthorized tool call
- [ ] Shadow results cannot affect users or business state
- [ ] Canary stages enforce samples, windows, telemetry, and guardrails
- [ ] Cost routing is explainable and quality constrained
- [ ] Incident Investigator cites evidence and states uncertainty
- [ ] Eligible regression rolls back safely to a known-good version
- [ ] Recovery is verified and fully audited

### Engineering

- [ ] Clean clone and one-command local setup work
- [ ] All required quality and test suites pass
- [ ] No flaky tests, secrets, PII, empty directories, or unused dependencies remain
- [ ] Migrations work from a clean database and documented supported upgrade point
- [ ] Images are non-root, scanned, and referenced by digest
- [ ] Terraform, Helm, and Kubernetes checks pass
- [ ] GitHub workflows use least privilege and OIDC

### Operations and documentation

- [ ] Dashboards and alerts are version controlled
- [ ] Runbooks cover every high-impact automated action
- [ ] Threat model and residual risks are published
- [ ] Azure costs and teardown are documented
- [ ] README claims match implemented behavior
- [ ] Architecture, API, manifest, evaluation, governance, and demo docs are current
- [ ] Phase 11 PR is merged and the green merge commit is tagged `v1.0.0`

---

## 18. Guiding principle

AgentHub should be impressive because its critical lifecycle is complete, explainable, tested, and safe—not because its dependency list is long.

Build the narrowest credible control plane that can prove:

> A candidate agent was registered, evaluated, governed, deployed, observed, found unhealthy, investigated with evidence, and safely rolled back.

That is the project.
