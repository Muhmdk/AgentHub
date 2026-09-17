"""Public project narrative, independent of database and provider availability."""

# HTML prose remains on logical lines to keep markup readable during review.
# ruff: noqa: E501, RUF001

from html import escape

NAV = (
    ("/", "Overview"),
    ("/how-it-works", "How it works"),
    ("/demo", "Lifecycle demo"),
    ("/try-locally", "Run locally"),
    ("/evidence", "Evidence"),
    ("/console", "Console"),
)
SOURCE = "https://github.com/Muhmdk/AgentHub"


def section(number: str, label: str, title: str, body: str) -> str:
    return (
        f'<section class="chapter"><p class="eyebrow">{number} / {label}</p>'
        f"<h2>{title}</h2>{body}</section>"
    )


def cards(items: list[tuple[str, str]]) -> str:
    return (
        '<div class="cards">'
        + "".join(f"<article><h3>{title}</h3><p>{body}</p></article>" for title, body in items)
        + "</div>"
    )


def code(value: str) -> str:
    return f'<div class="code-block"><pre><code>{escape(value)}</code></pre><button class="copy" type="button">Copy</button></div>'


def home() -> str:
    return (
        """<header class="hero"><p class="eyebrow">A project by Muhammad Khan · AgentOps / ModelOps</p>
    <h1>An AI agent passed its tests.<br><em>What happens when it fails in production?</em></h1>
    <p class="lede">AgentHub follows an agent from its first registered version to a carefully checked rollback.
    A working exploration of how to release AI software, control what it can do, and explain what went wrong.</p>
    <div class="actions"><a class="button primary" href="/demo">Explore the lifecycle <span>↗</span></a><a class="button" href="/how-it-works">Follow the engineering</a></div>
    <div class="hero-strip"><span>01 · Evaluate before release</span><span>02 · Observe every change</span><span>03 · Recover with evidence</span></div></header>"""
        + section(
            "01",
            "The starting point",
            "The answer is only the beginning.",
            '<p class="intro">An agent can answer a question correctly today and behave differently after a change to its model, instructions, tools, or retrieval settings. Who approved that change? Which users saw it? Can we undo it?</p>'
            + cards(
                [
                    (
                        "The problem",
                        "A successful chat response tells us little about whether a new version is safe to release. Teams also need identity, repeatable tests, permissions, operational evidence, and a recovery path.",
                    ),
                    (
                        "The project",
                        "AgentHub connects those responsibilities in one control plane. Three small retail agents give the infrastructure something concrete to operate.",
                    ),
                ]
            ),
        )
        + section(
            "02",
            "The workloads",
            "Three agents. One operating model.",
            cards(
                [
                    (
                        "Inventory",
                        "Uses structured retail data and read-only tools to identify stock risks. Example: which Toronto stores may run low on snow shovels?",
                    ),
                    (
                        "Knowledge",
                        "Retrieves policy documents and cites the evidence behind its answer. Example: can an unopened product be returned after 20 days?",
                    ),
                    (
                        "Shopping",
                        "Finds products within a customer’s constraints and cites catalogue evidence. Example: recommend a snow shovel under $60.",
                    ),
                ]
            ),
        )
        + section(
            "03",
            "The lifecycle",
            "A release has to earn its traffic.",
            '<ol class="journey">'
            + "".join(
                f"<li><span>{i:02}</span><strong>{title}</strong><p>{desc}</p></li>"
                for i, (title, desc) in enumerate(
                    [
                        ("Register", "Record an immutable version and its owner."),
                        ("Evaluate", "Block candidates that fail required checks."),
                        ("Govern", "Enforce permissions outside the model."),
                        ("Release gradually", "Compare shadow results and limit canary exposure."),
                        ("Observe", "Measure requests, latency, failures, and cost."),
                        (
                            "Investigate & recover",
                            "Cite evidence, restore a known-good route, verify health.",
                        ),
                    ],
                    1,
                )
            )
            + '</ol><a class="text-link" href="/demo">Walk through every transition →</a>',
        )
        + section(
            "04",
            "Engineering choices",
            "The decisions behind the screens.",
            cards(
                [
                    (
                        "Immutable identity",
                        "A registered version cannot silently change its manifest. Later evaluations and release evidence retain a trustworthy reference.",
                    ),
                    (
                        "A modular monolith",
                        "FastAPI composes separate domain modules around PostgreSQL transactions. This keeps local operation practical while making boundaries explicit.",
                    ),
                    (
                        "Policy outside the prompt",
                        "The model proposes actions; authorization code decides whether they may run. Prompts cannot grant permissions.",
                    ),
                    (
                        "Evidence before promotion",
                        "Canary guardrails require enough observations and healthy telemetry. Missing measurements block promotion.",
                    ),
                    (
                        "Analysis without actuation",
                        "Incident analysis cites persisted evidence. A separate coordinator checks and executes rollback intent.",
                    ),
                    (
                        "Execution is not recovery",
                        "A rollback can execute successfully while the service remains unhealthy. Recovery requires a separate observation window.",
                    ),
                ]
            ),
        )
        + section("05", "Architecture", "Follow the request. Follow the evidence.", architecture())
        + section(
            "06",
            "Failure design",
            "What happens when a dependency fails?",
            cards(
                [
                    (
                        "Policy unavailable",
                        "Authorization fails closed. The request does not proceed as if permission were granted.",
                    ),
                    (
                        "Candidate times out",
                        "Shadow failures are isolated from the stable response. Candidate observations retain a safe failure result.",
                    ),
                    (
                        "Database unavailable",
                        "Readiness reports failure; liveness remains separate. Connection pools and shutdown work are bounded.",
                    ),
                    (
                        "Rollback is repeated",
                        "The coordinator uses persisted state and idempotent operations to protect the route and audit trail.",
                    ),
                ]
            ),
        )
        + section("07", "Proof boundaries", "Know what you are looking at.", boundaries())
        + section("08", "Questions worth asking", "The tradeoffs are part of the project.", faq())
        + section(
            "09",
            "Explore further",
            "From explanation to execution.",
            '<p>Python · FastAPI · PostgreSQL · SQLAlchemy · Alembic · OPA · OpenTelemetry · Prometheus · Tempo · Grafana · Docker · Helm · Terraform</p><div class="actions"><a class="button primary" href="/try-locally">Run AgentHub locally</a><a class="button" href="/evidence">Inspect the evidence</a></div>',
        )
    )


def architecture() -> str:
    return """<div class="architecture" aria-label="Request and control-plane architecture">
    <div class="arch-row"><span>Caller</span><b>→</b><span>Gateway & identity</span><b>→</b><span>Policy & budgets</span><b>→</b><span>Agent / model / tools</span></div>
    <div class="arch-row"><span>Registry</span><b>→</b><span>Evaluation</span><b>→</b><span>Release & canary</span><b>→</b><span>Incident & rollback</span></div>
    <p>PostgreSQL stores versions, decisions, routes, and audit evidence.</p>
    <div class="arch-row"><span>OpenTelemetry Collector</span><b>→</b><span>Prometheus · metrics</span><span>Tempo · traces</span><span>Grafana · inspection</span></div></div>"""


def boundaries() -> str:
    return cards(
        [
            (
                "Implemented locally",
                "Real API handlers, PostgreSQL records, policy checks, evaluation gates, route transitions, audits, and telemetry instrumentation.",
            ),
            (
                "Synthetic inputs",
                "Fictional retail data, deterministic model outputs, seeded candidate observations, and an injected retrieval incident. These are repeatable fixtures.",
            ),
            (
                "Reference infrastructure",
                "Azure adapters, Terraform, and Helm are provided. This portfolio does not claim a running Azure deployment or production-scale validation.",
            ),
        ]
    )


def faq() -> str:
    return "".join(
        f"<details><summary>{q}</summary><p>{a}</p></details>"
        for q, a in [
            (
                "Why deterministic providers?",
                "They make regressions reproducible and keep the default demo free of paid model calls. Real-provider accuracy, latency, and cost require separate evaluation.",
            ),
            (
                "Why not use an existing agent platform?",
                "This project makes the lifecycle mechanisms inspectable: database constraints, policy boundaries, release state, and recovery evidence. It is a learning and engineering reference, not a claim to replace a managed platform.",
            ),
            (
                "What is the main engineering challenge?",
                "Keeping the facts consistent across versions, evaluation results, releases, traffic routes, and incidents. Immutable references and transactional state transitions make those relationships explicit.",
            ),
            (
                "How would this scale?",
                "The local baseline uses one API process. A deployment needs realistic provider tests, database connection budgeting, identity integration, and measured scaling behavior before capacity claims.",
            ),
            (
                "What would change next?",
                "A production deployment would need organization-specific access controls, operational ownership, deployment-specific recovery drills, and representative workloads. The current scope proves the local lifecycle.",
            ),
            (
                "How do I add an agent?",
                "Implement the runtime contract, declare its model and tools in a manifest, supply evaluation fixtures and gates, and register a version. Then exercise the same governance and release boundaries.",
            ),
        ]
    )


def how() -> str:
    steps = [
        (
            "Register an exact version",
            "The manifest ties owner, source, tools, provider settings, and evaluation configuration to an immutable identity. Repeating an identical registration is safe; replacing the content of an existing version is rejected.",
            "packages/registry",
            "/registry",
        ),
        (
            "Evaluate against requirements and a baseline",
            "Versioned datasets and gates measure correctness, groundedness, tool use, safety, latency, and cost. Required failures block release progression. Comparison against a baseline makes regressions visible.",
            "packages/evaluation",
            "/evaluations",
        ),
        (
            "Authorize each action",
            "The gateway authenticates callers. Governed model and tool wrappers enforce policy and budgets outside the model. Local mode has explicit development identities; production requires configured credentials.",
            "packages/governance",
            "/governance",
        ),
        (
            "Release through explicit states",
            "Candidate releases carry source and evaluation references. Promotion checks the current state and required evidence. Database transactions and revisions protect concurrent changes.",
            "packages/release",
            "/delivery",
        ),
        (
            "Compare in shadow, then limit exposure",
            "Shadow execution retains the stable response and isolates candidate effects. Canary stages require paired samples, observation windows, telemetry, and quality, safety, latency, error, and cost guardrails.",
            "packages/delivery",
            "/delivery",
        ),
        (
            "Measure the request path",
            "OpenTelemetry records runtime observations and traces. Prometheus stores exported metrics, Tempo stores traces, and Grafana provides inspection. In-process fleet measurements reset when the API process restarts.",
            "packages/observability",
            "/observability",
        ),
        (
            "Collect evidence before drawing conclusions",
            "An incident trigger links affected release and runtime evidence. The local deterministic analyzer cites content-addressed evidence and communicates uncertainty; it does not have deployment credentials.",
            "packages/incidents",
            "/incidents-console",
        ),
        (
            "Derive a safe rollback on the server",
            "The browser sends intent. The coordinator checks persisted incident, route, canary, gate, and release state to choose an eligible known-good target. Route changes and audit events are controlled together.",
            "packages/incidents/coordinator.py",
            "/incidents-console",
        ),
        (
            "Verify recovery separately",
            "Requested, executed, verifying, and recovered are distinct states. The operator click does not fabricate a recovery window. The deterministic E2E scenario supplies observations to test the full recovery path.",
            "tests/e2e/test_demo_lifecycle.py",
            "/evidence",
        ),
    ]
    return (
        '<header class="page-head"><p class="eyebrow">Engineering notebook</p><h1>How the pieces<br><em>work together.</em></h1><p class="lede">Follow one candidate through the control plane. Each decision has a reason, a failure boundary, and inspectable code.</p></header>'
        + architecture()
        + "".join(
            section(
                f"{i:02}",
                "Lifecycle",
                title,
                f'<p class="intro">{body}</p><div class="actions"><a class="text-link" href="{SOURCE}/tree/main/{path}">Inspect source ↗</a><a class="text-link" href="{route}">Open console →</a></div>',
            )
            for i, (title, body, path, route) in enumerate(steps, 1)
        )
    )


def local() -> str:
    return (
        '<header class="page-head"><p class="eyebrow">Run the implementation</p><h1>See the evidence<br><em>on your machine.</em></h1><p class="lede">A deterministic demo using the real API, database, and observability services. No model API key is needed.</p></header>'
        + section(
            "01",
            "Prerequisites",
            "Prepare your machine.",
            "<p>Python 3.14, Docker with Compose, GNU Make, and Git. Docker must be running. The default PostgreSQL port is 5433; the API uses 8000 and Grafana uses 3000.</p>",
        )
        + section(
            "02",
            "Start",
            "One command starts the story.",
            code("git clone https://github.com/Muhmdk/AgentHub.git\ncd AgentHub\nmake demo")
            + "<p>This installs locked dependencies, starts PostgreSQL and telemetry services, applies migrations, resets allowlisted local demo tables, seeds the scenario, and starts the API with tracing enabled. Keep that terminal open. Resetting replaces existing AgentHub demo records.</p><p>Expected: healthy services, three registered agents, generated scenario IDs, and “Application startup complete.”</p>",
        )
        + section(
            "03",
            "Inspect",
            "Open the console, then send a request.",
            '<p>Open <a href="http://127.0.0.1:8000/console">localhost:8000/console</a>. In a second terminal:</p>'
            + code(
                "curl -sS http://127.0.0.1:8000/gateway/agents/knowledge-agent/invoke \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AgentHub-Identity: local/demo' \\\n  -d '{\"query\":\"Can I return an unopened product after 20 days?\",\"seed\":4}'"
            )
            + "<p>Expect a grounded answer with citations. Open Observability to inspect the request and follow its trace into Grafana.</p>",
        )
        + section(
            "04",
            "Exercise recovery",
            "Follow the incident to rollback.",
            '<p>Use the live mode of the <a href="/demo">guided demo</a>. Inspect the seeded retrieval regression, then open Incidents to request a policy-checked rollback. Candidate traffic should return to zero; recovery still requires post-rollback observations.</p>',
        )
        + section(
            "05",
            "Verify safely",
            "Run tests against an isolated database.",
            "<p>The database-backed test fixtures clear AgentHub tables. Use a disposable test database, never your active demo or valuable data. Without a test database URL, database-dependent tests skip.</p>"
            + code(
                'AGENTHUB_DATABASE_URL="<disposable PostgreSQL test database URL>" make test-e2e'
            )
            + "<p>The live observability test is separately opt-in. See the repository’s test fixtures and CI workflow for the complete environment.</p>",
        )
        + section(
            "06",
            "Reset and stop",
            "Keep a repeatable starting point.",
            code(
                "# Stop the API with Ctrl+C first.\nmake demo  # resets the local scenario and enables tracing\n\n# To stop after the demo, press Ctrl+C, then:\nmake observability-down\nmake down"
            )
            + "<p>Stopping services preserves the database volume. <code>make run</code> alone does not enable the telemetry settings supplied by <code>make demo</code>.</p>",
        )
        + section(
            "07",
            "Troubleshooting",
            "Check the boundary that failed.",
            cards(
                [
                    (
                        "Port already in use",
                        "Stop the earlier API process before starting another. Restart after changing Python source.",
                    ),
                    (
                        "No metrics or trace link",
                        "Invoke an agent after startup and ensure telemetry is enabled. Empty measurements mean no observations, not perfect health.",
                    ),
                    (
                        "Old incident IDs",
                        "A reset creates new scenario IDs. Refresh your console and select the newly seeded incident.",
                    ),
                ]
            ),
        )
    )


def evidence() -> str:
    return (
        '<header class="page-head"><p class="eyebrow">Evidence & limits</p><h1>Claims you can<br><em>inspect.</em></h1><p class="lede">Recorded results, reproducible commands, and the boundaries of what this project demonstrates.</p></header>'
        + section(
            "01",
            "Validation snapshot",
            "A tested lifecycle.",
            '<p>At the root-route hotfix validation on September 15, 2026: 537 tests passed, one optional telemetry test skipped, and measured coverage was 92.08%. These are a historical snapshot, not a live CI badge.</p><div class="actions"><a class="button" href="https://github.com/Muhmdk/AgentHub/actions/runs/35015729424">Inspect the successful workflow ↗</a><a class="button" href="https://github.com/Muhmdk/AgentHub/actions">Current CI ↗</a></div>',
        )
        + section(
            "02",
            "Local performance",
            "Measure before making capacity claims.",
            '<p>Recorded September 14, 2026 EDT: Apple M2 Pro, 16 GiB RAM, Python 3.14.3, one Uvicorn process, local PostgreSQL, deterministic providers, loopback traffic.</p><div class="table-wrap"><table><caption>Historical control-plane baseline</caption><thead><tr><th scope="col">Endpoint</th><th scope="col">Requests / concurrency</th><th scope="col">Failures</th><th scope="col">Throughput</th><th scope="col">p95</th></tr></thead><tbody><tr><td>/health/live</td><td>500 / 20</td><td>0</td><td>2,176.66 req/s</td><td>26.52 ms</td></tr><tr><td>/observability/fleet</td><td>100 / 8</td><td>0</td><td>285.46 req/s</td><td>105.99 ms</td></tr></tbody></table></div><p>These endpoints do not measure model inference throughput or production capacity. Network, cloud providers, and realistic user traffic require separate measurements.</p>'
            + f'<a class="text-link" href="{SOURCE}/blob/main/docs/performance-and-resilience.md">Methodology, commands & resilience report ↗</a>',
        )
        + section(
            "03",
            "Verification layers",
            "More than a successful response.",
            cards(
                [
                    (
                        "Contracts & integration",
                        "HTTP responses, schema validation, database migrations, governance denies, concurrency boundaries, and immutable records.",
                    ),
                    (
                        "End-to-end recovery",
                        "Registration, evaluation, releases, canaries, evidence, rollback, recovery verification, and audit ordering.",
                    ),
                    (
                        "Supply chain & deployment",
                        "Locked dependencies, secret and vulnerability scans, OPA policy tests, non-root containers, Helm and Terraform validation.",
                    ),
                ]
            )
            + f'<p><a href="{SOURCE}/tree/main/tests">Browse tests</a> · <a href="{SOURCE}/tree/main/.github/workflows">Browse workflows</a> · <a href="{SOURCE}/blob/main/docs/security/threat-model.md">Threat model and residual risks</a></p>',
        )
        + section("04", "Boundaries", "Local proof, explicit limits.", boundaries())
    )


CONSOLES = [
    ("/registry", "Registry", "Inspect registered agents, owners, and immutable version history."),
    (
        "/evaluations",
        "Evaluations",
        "Compare a failing Inventory candidate against a passing baseline.",
    ),
    (
        "/governance",
        "Governance",
        "Filter the audit to Deny and inspect the undeclared admin.delete attempt.",
    ),
    (
        "/observability",
        "Observability",
        "Invoke an agent first, then inspect measured request health and trace links.",
    ),
    (
        "/delivery",
        "Delivery",
        "Inspect stable and candidate traffic, canary guardrails, and cost projections.",
    ),
    (
        "/incidents-console",
        "Incidents",
        "Read evidence, request eligible rollback, and distinguish execution from recovery.",
    ),
]


def console() -> str:
    return (
        '<header class="page-head"><p class="eyebrow">Operator workspace</p><h1>Inspect the<br><em>running system.</em></h1><p class="lede">These consoles read your local API. Seeded scenario records are synthetic; runtime measurements come from your API process.</p></header><div class="cards">'
        + "".join(
            f'<article><p class="eyebrow">{i:02} / Console</p><h2>{title}</h2><p>{desc}</p><a class="text-link" href="{route}">Open {title.lower()} →</a></article>'
            for i, (route, title, desc) in enumerate(CONSOLES, 1)
        )
        + '</div><p class="console-help">New to AgentHub? <a href="/demo?mode=live">Follow the guided local walkthrough</a>. <a href="/docs">Explore the API</a>.</p>'
    )


def demo() -> str:
    return """<header class="page-head compact"><p class="eyebrow">Interactive walkthrough</p><h1>Follow a release.<br><em>Understand the recovery.</em></h1><p class="lede">Move through the lifecycle at your pace. Every step explains its purpose and the evidence you should inspect.</p></header>
    <div class="demo-toolbar"><label for="demo-mode">Experience</label><select id="demo-mode"><option value="preview">Browser simulation</option><option value="live">Local API walkthrough</option></select><button id="demo-reset" type="button">Restart walkthrough</button></div>
    <p id="mode-notice" class="notice"></p><div class="demo-layout"><nav id="demo-steps" aria-label="Lifecycle stages"></nav><section class="demo-stage" aria-labelledby="stage-title"><p id="stage-count" class="eyebrow"></p><h2 id="stage-title"></h2><p id="stage-description" class="intro"></p><div id="stage-evidence"></div><p id="stage-status" role="status" aria-live="polite"></p><div class="actions"><button id="stage-action" class="primary" type="button">Inspect evidence</button><a id="stage-console" class="button" href="/console">Open console ↗</a></div><details><summary>Inspect response or illustrative record</summary><pre id="stage-raw"></pre></details><div class="demo-controls"><button id="demo-prev" type="button">← Previous</button><button id="demo-next" type="button">Next stage →</button></div></section></div>
    <section class="chapter"><p class="eyebrow">Walkthrough history</p><ol id="demo-events" class="events" aria-live="polite"></ol></section>
    <script src="/assets/demo.js" defer></script>"""


PAGES = {
    "/": ("Overview", home),
    "/how-it-works": ("How it works", how),
    "/try-locally": ("Run locally", local),
    "/evidence": ("Evidence", evidence),
    "/console": ("Operator console", console),
    "/demo": ("Lifecycle demo", demo),
}


def render_page(path: str) -> str:
    title, content = PAGES[path]
    nav = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if url == path else "") + f">{label}</a>"
        for url, label in NAV
    )
    description = "AgentHub by Muhammad Khan: an inspectable AI agent lifecycle from registration and evaluation to evidence-based rollback."
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} · AgentHub by Muhammad Khan</title><meta name="description" content="{description}"><meta property="og:title" content="{title} · AgentHub"><meta property="og:description" content="{description}"><meta name="twitter:card" content="summary"><link rel="stylesheet" href="/assets/agenthub.css"><script src="/assets/shell.js" defer></script></head>
    <body class="portfolio"><a class="skip-link" href="#main-content">Skip to main content</a><nav class="site-nav" aria-label="Main navigation"><a class="brand" href="/">A<span>↗</span></a>{nav}<button class="theme-toggle" type="button" aria-label="Switch color theme">◐</button></nav>
    <main id="main-content" tabindex="-1">{content()}</main><footer><a class="brand" href="/">AgentHub</a><p>Designed and built by Muhammad Khan.<br>Local implementation · synthetic demo inputs · inspectable evidence.</p><a href="{SOURCE}">Source on GitHub ↗</a></footer></body></html>'''
