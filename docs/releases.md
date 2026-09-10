# Release pipeline

AgentHub turns one source commit into one scanned image and promotes that exact digest. Staging
and production never rebuild it. The control plane stores the corresponding source SHA, manifest
hash, image digest, evaluation run and artifact hash, SBOM digest, build-provenance digest, policy
decision, gate result, and append-only transition history.

## Workflow boundaries

| Workflow | Trigger | Responsibility | Default token permission |
|---|---|---|---|
| `PR CI` | pull request and `main` push | static checks, all test classes, dependency/secret scans, image smoke test | `contents: read` |
| `Candidate Evaluation` | reusable or manual | register the digest-bound manifest, evaluate it, create the candidate, upload evidence | `contents: read` |
| `Release` | published GitHub release or manual | build once, publish, scan, attest, evaluate, request approvals, record promotion receipts | `contents: read` |
| `Infrastructure Validation` | infrastructure pull request paths or manual | validate Compose, migrations, dashboards, alerts, and container build | `contents: read` |

Only the release build job receives `packages: write`, `attestations: write`, and `id-token:
write`. Promotion jobs receive only `contents: read` and `id-token: write`. No workflow uses a
stored cloud or registry password: GHCR uses the short-lived workflow token and environments mint
audience-bound GitHub OIDC tokens.

All third-party actions and service containers are pinned by commit SHA or image digest. Trivy
fails release publication for an unfixed `HIGH` or `CRITICAL` image vulnerability. The dependency
audit fails on known vulnerable locked Python packages, and the secret scan covers tracked files.

## Candidate and state model

```text
source SHA + image digest + manifest hash
              │
              ├── evaluation artifact
              ├── SBOM and build provenance
              ├── security attestation
              └── policy decision
                       │
                    evaluated
                       │ all gates pass
                    approved
                       │ staging approval
                     staged
                       │ production approval
                   production
```

`rejected` and `failed` are explicit terminal/recovery states. A blocked technical or policy gate
cannot enter `approved`, `staged`, or `production`. Every candidate and transition takes an
idempotency key. Repeating the same request returns the existing release; reusing a key with
different lineage or intent returns a conflict.

## Local verification

Start and migrate PostgreSQL, then exercise both required outcomes:

```bash
make up
make migrate
make simulate-release
make simulate-release-bad
```

The first command exits `0`, reports `production`, four events, and successful candidate and
promotion replay. The second deliberately corrupts evaluation behavior, exits `2`, reports
`evaluation_gate_failed`, and remains `evaluated` with one creation event.

Use `python -m packages.release --help` for lower-level candidate and promotion commands. API
clients can use `/releases/candidates`, `/releases/{id}/transitions`, `/releases/{id}/events`, and
`/releases/{id}/notes` for the same persisted behavior.

## Publication evidence

Each release run uploads:

- the CycloneDX image and Python dependency SBOMs;
- GitHub-signed build-provenance and SBOM attestations for the digest;
- the complete immutable evaluation report and candidate release record;
- `release-provenance.json`, tying build and control-plane evidence together;
- human-readable `release-notes.md`;
- staging and production receipts containing the digest and stable retry key.

The environment receipts are workflow evidence. A real deployment adapter must use the release
API to persist the matching transition before it reports a deployment complete; it must never
infer state from a mutable tag.

## Protected environments

The repository environments `staging` and `production` accept protected branches only and require
approval by the `Muhmdk` account. Self-review prevention is disabled because this reference
repository has one maintainer; the approval click is still mandatory. Add independent reviewers
and enable self-review prevention before using this setup for a multi-operator production system.

See the [release recovery runbook](runbooks/release-recovery.md) before rerunning or rejecting a
failed release.
