# Database backup, restore, and migration recovery

AgentHub stores immutable registry, evaluation, release, delivery, incident, evidence, rollback, and
audit records in PostgreSQL. Configure managed backups and point-in-time recovery in the deployment
environment; this repository does not schedule or retain production backups.

## Before a migration

1. Stop new promotions and rollback requests. Record the current application image digest and
   `alembic current` revision.
2. Verify the managed backup retention and most recent successful restore test.
3. Create an encrypted, access-controlled logical backup when policy requires one. Supply a native
   PostgreSQL URL through `AGENTHUB_PG_URL`; do not put credentials in shell history or source files.

```bash
pg_dump --format=custom --no-owner --file=agenthub-pre-migration.dump "$AGENTHUB_PG_URL"
sha256sum agenthub-pre-migration.dump
```

4. Store the checksum, backup location, database server/version, application digest, migration head,
   operator, and retention expiry in the change record.

## Verify migration state

Run migrations as a dedicated job before starting the new application revision:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

`/health/ready` requires both a successful database ping and the exact schema revision expected by
the running application. A reachable database on an older or unknown revision remains unready, so a
rolling deployment cannot send traffic to a mismatched pod.

## Restore drill

Restore into a new empty database, never over the only production copy:

```bash
createdb "$AGENTHUB_RESTORE_DATABASE"
pg_restore --exit-on-error --no-owner --dbname="$AGENTHUB_RESTORE_PG_URL" agenthub-pre-migration.dump
AGENTHUB_DATABASE_URL="$AGENTHUB_RESTORE_SQLALCHEMY_URL" .venv/bin/alembic current
```

Then start AgentHub against the isolated restore and verify:

- `/health/ready` returns `200`;
- agent/version, release, route/canary, incident/evidence, and rollback counts match the source;
- every current record has its expected append-only event chain;
- stored manifest, evaluation, evidence, command, and provenance hashes are unchanged;
- the canonical lifecycle E2E passes against a separate disposable database.

Record recovery-point and recovery-time measurements. Destroy the restore only after the result and
checksum are reviewed.

## Failed migration

Do not edit `alembic_version` or application tables manually. Keep the new pods unready, preserve the
failed job logs, and determine whether the migration transaction rolled back. Prefer fixing a
forward migration and rerunning it. Use an Alembic downgrade only when that revision includes a
reviewed downgrade and no newer application has written incompatible data.

If data integrity is uncertain, restore the last verified backup into a new server, validate hashes
and event chains, update the database secret through the approved deployment path, then restart the
rollout. Capture the original server for forensic review.

## Pool exhaustion and disruption

Each process defaults to five persistent connections, ten bounded overflow connections, and a
five-second checkout timeout. Size total PostgreSQL capacity for the maximum pod count plus migration
jobs and operator headroom. A checkout timeout is a capacity incident, not permission to create an
unbounded pool.

On Kubernetes, readiness removes draining or schema-mismatched pods before traffic. The API bounds
dependency cleanup to ten seconds within the 30-second pod grace period. Rolling updates use zero
unavailable pods and one surge pod. The development profile intentionally leaves the disruption
budget disabled while minimum replicas is one; enable it only with at least two ready replicas, or
voluntary drains can become impossible.
