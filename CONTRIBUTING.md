# Contributing to AgentHub

AgentHub is delivered one phase at a time. Read [AGENTHUB_PLAN.md](AGENTHUB_PLAN.md), this
guide, the active phase, and relevant ADRs before editing code.

## Development workflow

1. Start from an updated, green `main` branch.
2. Create the exact phase branch named in the plan. Do not commit directly to `main`.
3. Implement only the active phase as small, complete vertical slices.
4. Add deterministic tests with the behavior and keep local workflows free of paid calls.
5. Run the full local quality suite before requesting review.
6. Open one pull request using the required phase title and the repository template.

Use Conventional Commits with a focused scope, for example:

```text
feat(api): add health and version endpoints
test(api): cover service health contracts
fix(config): reject invalid environment names
docs(adr): explain service boundary decision
chore(ci): update locked quality tools
```

Do not use `Co-authored-by` trailers unless the named person actually contributed and
explicitly wants that attribution. Commits use the author identity configured in Git; verify
it before committing with:

```bash
git config user.name
git config user.email
```

## Required local checks

```bash
make lint
make typecheck
make test
make security
```

For a clean environment, run `make setup` first. Each commit should leave the branch runnable.
Do not commit `.env`, virtual environments, coverage files, logs, generated binaries, local
databases, provider credentials, or cloud state.

## Pull requests

Phase 00 uses the title `Phase 00: Establish AgentHub foundation`. Keep the PR description
current and include:

- the phase objective and completed scope;
- exact verification commands and results;
- operational or security considerations;
- evidence such as output, reports, or screenshots when useful;
- known risks, intentionally deferred work, and rollback notes.

CI must be green and review comments resolved before merge. A later phase must not be stacked
on an unfinished phase.
