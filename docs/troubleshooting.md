# Troubleshooting index

Start with the safe public endpoints:

```console
curl --fail-with-body http://127.0.0.1:8000/health/live
curl --fail-with-body http://127.0.0.1:8000/health/ready
curl --fail-with-body http://127.0.0.1:8000/version
```

Liveness proves only that the process serves HTTP. Readiness additionally requires a
database connection and this checkout's exact migration revision. Application errors use
safe codes and correlation IDs; inspect structured logs by correlation ID without logging
raw prompts, credentials, or PII.

## Local development

| Symptom | Check | Resolution |
| --- | --- | --- |
| Python/venv command missing | `python3.14 --version` and `.venv/bin/python --version` | install Python 3.14, then `make setup` |
| PostgreSQL does not start | `docker compose ps postgres` and `docker compose logs postgres` | free host port 5433 or correct the explicit local override; rerun `make up` |
| Readiness says database unavailable | `make migrate`; `.venv/bin/alembic current` | start PostgreSQL and migrate; never create tables manually |
| Demo reset refuses | inspect environment/provider/database settings, not secret values | restore documented local defaults and run `make demo-reset` |
| Evaluation intentionally exits 2 | inspect gate reasons in JSON or `/evaluations` | expected for `make evaluate-bad`; fix candidate inputs for an unexpected failure |
| Console shows an API error | inspect the matching endpoint and correlation ID | repair the dependency; the page will not substitute fixture values |
| No traces in Grafana | confirm `make observability-up` and `AGENTHUB_OTEL_ENABLED=true` | follow the [telemetry runbook](runbooks/telemetry-backend.md) |

`make clean` removes only generated local test/lint reports. `make down` stops Compose
services but preserves volumes. Neither command resets demo data; use the explicitly
guarded `make demo-reset` when that is the intended action.

## Azure reference deployment

CI validates Azure Terraform/Helm definitions but does not provision them. Begin with
[Azure troubleshooting](runbooks/azure-troubleshoot.md) for migration hooks, pod readiness,
workload identity, OpenAI, Search, and Monitor failures. Use the provider, policy, database,
or incident runbook from the [operator index](runbooks/README.md) once the failing boundary
is known.

Do not weaken private networking, pod security, workload identity, OPA, audit persistence,
or readiness to make a deployment appear healthy. Fix the declarative source through a
reviewed change and re-run validation/smoke checks.

## Explicitly not implemented

There is no automatic provider failover, multi-region traffic manager, hosted SaaS tenant
console, external identity directory, or autonomous remediation controller. If a guide or
issue proposes one of these, treat it as future design—not an available troubleshooting
step. Current recovery uses the immutable release, policy, route, and runbook mechanisms
documented in this repository.
