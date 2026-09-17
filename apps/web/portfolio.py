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
        """<header class="hero"><p class="eyebrow">A project by Muhammad Khan · Building safer AI systems</p>
    <h1>Your AI works in a test.<br><em>What happens when something goes wrong?</em></h1>
    <p class="lede">AgentHub is a project for testing and running AI assistants.
    It checks new versions, limits what they can do, and helps you find and undo a bad change.</p>
    <div class="actions"><a class="button primary" href="/demo">Explore the lifecycle <span>↗</span></a><a class="button" href="/how-it-works">Follow the engineering</a></div>
    <div class="hero-strip"><span>01 · Test before use</span><span>02 · Watch for problems</span><span>03 · Check that the fix worked</span></div></header>"""
        + section(
            "01",
            "The starting point",
            "The answer is only the beginning.",
            '<p class="intro">An AI agent is software that can answer questions and use tools to do a task. A small change to its settings can make a good answer wrong or slow. Who made the change? Which version handled the request? Can we go back?</p>'
            + cards(
                [
                    (
                        "The problem",
                        "One good answer does not prove an AI assistant is ready for people to use. We need to test it, check its access, and keep records that help us fix problems.",
                    ),
                    (
                        "The project",
                        "AgentHub brings these checks into one place. It uses three store assistants to show the full process, from saving a new version to fixing a failed update.",
                    ),
                ]
            ),
        )
        + section(
            "02",
            "The demo assistants",
            "Three useful jobs. The same safety checks.",
            cards(
                [
                    (
                        "Inventory",
                        "Checks store stock without changing it. For example: which Toronto stores may run low on snow shovels?",
                    ),
                    (
                        "Knowledge",
                        "Looks up store rules and shows where its answer came from. For example: can I return an unopened product after 20 days?",
                    ),
                    (
                        "Shopping",
                        "Finds products that match what a shopper needs, using the store catalogue. For example: find a snow shovel under $60.",
                    ),
                ]
            ),
        )
        + section(
            "03",
            "Step by step",
            "Check a new version before more people use it.",
            '<ol class="journey">'
            + "".join(
                f"<li><span>{i:02}</span><strong>{title}</strong><p>{desc}</p></li>"
                for i, (title, desc) in enumerate(
                    [
                        (
                            "Save a version",
                            "Record its settings and who owns it. Keep that record unchanged.",
                        ),
                        ("Run tests", "Stop a new version if it fails a required check."),
                        ("Check access", "Let code decide which tools the AI is allowed to use."),
                        (
                            "Start small",
                            "Compare the new version with the old one. Send it only a small share of requests.",
                        ),
                        ("Watch results", "Track response time, errors, and cost."),
                        (
                            "Find and fix problems",
                            "Read the saved records, switch back to a working version, and check the results.",
                        ),
                    ],
                    1,
                )
            )
            + '</ol><a class="text-link" href="/demo">Try each step →</a>',
        )
        + section(
            "04",
            "Engineering choices",
            "The decisions behind the screens.",
            cards(
                [
                    (
                        "Saved versions stay the same",
                        "Once a version is saved, its settings cannot be replaced under the same version number. Tests and release records still point to the exact version they checked.",
                    ),
                    (
                        "One app, separate parts",
                        "The app runs as one service, with separate code for tests, access rules, releases, and repairs. PostgreSQL transactions save related changes together, so a half-finished update does not become the new state.",
                    ),
                    (
                        "The AI cannot give itself access",
                        "The AI can ask to use a tool. Separate code checks whether it is allowed. Changing the AI's instructions does not give it more access.",
                    ),
                    (
                        "No data means no wider release",
                        "The new version must have enough test results and recent measurements before it gets more requests. Missing data does not count as a pass.",
                    ),
                    (
                        "Finding a cause does not grant control",
                        "The part that explains a failure points to saved records. It cannot change a running release. Separate code checks whether switching back is allowed and carries out that change.",
                    ),
                    (
                        "A completed change is not a proven fix",
                        "Switching back to an older version is called a rollback. That step can finish while the service still has problems. New measurements must show that it is working again.",
                    ),
                ]
            ),
        )
        + section("05", "How it is built", "Where a request goes.", architecture())
        + section(
            "06",
            "When things break",
            "What if part of the system stops working?",
            cards(
                [
                    (
                        "The access check is down",
                        "The request stops. The system does not assume that a missing check means permission was granted.",
                    ),
                    (
                        "The test version is too slow",
                        "During a background comparison, the user still gets the current version's answer. A slow test version is recorded as a failure instead of breaking that answer.",
                    ),
                    (
                        "The database is down",
                        "The service reports that it is not ready to handle work. A separate check shows whether the app itself is still running. Database connections have limits.",
                    ),
                    (
                        "Someone asks for the same fix twice",
                        "The system checks what has already happened before changing where requests go. Repeating a rollback request should not create a second, conflicting change.",
                    ),
                ]
            ),
        )
        + section("07", "What is real", "What this demo does and does not show.", boundaries())
        + section("08", "Common questions", "Why build it this way?", faq())
        + section(
            "09",
            "Explore further",
            "Try it on your computer.",
            '<p>Python · FastAPI · PostgreSQL · SQLAlchemy · Alembic · OPA · OpenTelemetry · Prometheus · Tempo · Grafana · Docker · Helm · Terraform</p><div class="actions"><a class="button primary" href="/try-locally">Run AgentHub locally</a><a class="button" href="/evidence">Inspect the evidence</a></div>',
        )
    )


def architecture() -> str:
    return """<div class="architecture" aria-label="Request and control-plane architecture">
    <div class="arch-row"><span>User sends a request</span><b>→</b><span>Check who sent it</span><b>→</b><span>Check access and spending limits</span><b>→</b><span>AI uses allowed tools</span></div>
    <div class="arch-row"><span>Save a version</span><b>→</b><span>Run tests</span><b>→</b><span>Try a small release</span><b>→</b><span>Find problems and switch back</span></div>
    <p>PostgreSQL is the database. It keeps the version history and records of what changed and why.</p>
    <div class="arch-row"><span>OpenTelemetry collects measurements</span><b>→</b><span>Prometheus stores counts and timings</span><span>Tempo stores the steps of each request</span><span>Grafana shows the results</span></div></div>"""


def boundaries() -> str:
    return cards(
        [
            (
                "Working software",
                "The app runs real code for tests, access checks, releases, and rollback. It saves records in PostgreSQL and measures requests handled by the running app.",
            ),
            (
                "Made-up demo data",
                "The store data, sample AI answers, and staged failure are made for this demo. The same inputs give the same results, so you can repeat the test without paying for an AI service.",
            ),
            (
                "Cloud setup still needs testing",
                "The repo includes code and setup files for Azure. This page shows the local project, not a live cloud service or proof that it can handle a large number of real users.",
            ),
        ]
    )


def faq() -> str:
    return "".join(
        f"<details><summary>{q}</summary><p>{a}</p></details>"
        for q, a in [
            (
                "Why use fixed sample AI answers?",
                "They let you repeat the same test and see the same failure without paying for an AI service. A real model can give different answers. Its accuracy, speed, and cost would need separate tests.",
            ),
            (
                "Why build this instead of using an existing platform?",
                "The goal is to show how the checks work underneath the screens. You can read the code that blocks a release, checks access, and handles a failed update. This project is for learning and testing these ideas; it does not claim to replace a hosted platform.",
            ),
            (
                "What is the hardest part of the design?",
                "Keeping every record tied to the right version. A test result is only useful if it describes the version being released. Saved version records cannot be replaced, and related database changes are saved together.",
            ),
            (
                "Could it handle more users?",
                "That needs testing. The local demo runs one app process. Before adding more users, I would test real AI services, set database connection limits, connect user accounts, and measure where the system slows down.",
            ),
            (
                "What is needed before a company could use it?",
                "The team would need its own access rules, people responsible for running the service, tests based on real tasks, and practice recovering from failures. The current project shows the process on a local machine.",
            ),
            (
                "How do I add another AI assistant?",
                "Write its task code and a settings file that lists its model and tools. Add sample questions and rules for passing the tests. Save a version, then run it through the same access checks and release steps.",
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
    description = "AgentHub by Muhammad Khan: test AI assistants, control their access, and find and undo bad changes."
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} · AgentHub by Muhammad Khan</title><meta name="description" content="{description}"><meta property="og:title" content="{title} · AgentHub"><meta property="og:description" content="{description}"><meta name="twitter:card" content="summary"><link rel="stylesheet" href="/assets/agenthub.css"><script src="/assets/shell.js" defer></script></head>
    <body class="portfolio"><a class="skip-link" href="#main-content">Skip to main content</a><nav class="site-nav" aria-label="Main navigation"><a class="brand" href="/">A<span>↗</span></a>{nav}<button class="theme-toggle" type="button" aria-label="Switch color theme">◐</button></nav>
    <main id="main-content" tabindex="-1">{content()}</main><footer><a class="brand" href="/">AgentHub</a><p>Designed and built by Muhammad Khan.<br>Runs locally · uses sample data · shows how decisions were made.</p><a href="{SOURCE}">Code on GitHub ↗</a></footer></body></html>'''
