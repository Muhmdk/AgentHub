# Portfolio presentation

AgentHub serves its employer-facing project story at `/`. The shared style uses
editorial headings, a quiet blueprint grid, a teal accent, and light/dark themes.
The presentation is inspired by the structure of https://ckpt.tasfiqj.com/;
its text, implementation, and project claims are specific to AgentHub.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Problem, workloads, lifecycle, decisions, architecture, limits, and Q&A |
| `/how-it-works` | Technical explanation with source and console links |
| `/demo` | Twelve-stage browser simulation or local evidence walkthrough |
| `/try-locally` | Setup, request example, verification, reset, and troubleshooting |
| `/evidence` | Dated validation snapshot and measured performance methodology |
| `/console` | All six API-backed operator consoles |

Existing console and API routes retain their behavior. Restart the Python API after
updating it. The portfolio replaces the previous root-to-registry redirect.

## Demo modes

Browser simulation starts by default. Its records are illustrative and selecting a
stage never calls the backend. Local mode is explicit and reads the current server's
API with bounded timeouts. Failures stay visible instead of becoming simulated success.
Use `/demo?mode=live` to enter local mode directly.

The local guide links to the actual console for comparisons and rollback. It does not
perform rollback or reset the database when navigating, inspecting evidence, changing
mode, or restarting the walkthrough. Run `make demo` from the terminal to seed/reset
the real local scenario. That command replaces allowlisted demo records.

Public narration and simulation do not require database reads. Existing production
authentication remains enforced; this change does not publish a public cloud service.

## Presenter sequence

1. Explain the question on the home page and the three retail workloads.
2. Open the guided demo and show the blocked candidate and denied tool.
3. In local mode, inspect actual records and invoke an agent using the provided command.
4. Follow the trace through Observability; inspect the canary in Delivery.
5. Open Incidents, read citations, request rollback, and explain recovery verification.
6. Close with Evidence, the limitations, and the reproducible local setup.

The evidence page identifies its test counts as a historical snapshot. Update that
snapshot only with a new dated result. Local control-plane benchmarks do not represent
model inference throughput or a production capacity guarantee.

## Development

`apps/web/portfolio.py` renders semantic HTML with shared assets in `apps/web/assets`.
The operator consoles load the same theme and navigation. No frontend runtime dependency
is required. Wheel packaging includes the assets; clean-install verification checks them.
The guide's database-backed tests require a disposable test database because fixtures
clear AgentHub tables. Never run them against an active demo or valuable records.
