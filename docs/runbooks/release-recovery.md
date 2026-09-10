# Release failure and recovery runbook

Use this runbook when candidate evaluation, scanning, attestation, approval, or promotion fails.
Do not rebuild an image to recover a partially completed release. Recovery always refers to the
original digest and candidate release ID.

## Triage

1. Open the failed GitHub Actions run and record its run ID, source SHA, image digest, candidate
   release ID, and provenance hash.
2. Download the build, candidate, and release evidence artifacts that exist. Verify the image
   reference ends in the recorded `@sha256:` digest.
3. Inspect `/releases/{release_id}` and `/releases/{release_id}/events`. Treat the database state
   and append-only events as authoritative; a workflow receipt alone is not a state transition.
4. Classify the failure before acting.

| Failure | Expected state | Recovery |
|---|---|---|
| format, type, test, dependency, or secret check | no candidate | fix source and open a new candidate |
| high/critical image finding | no promotion | fix dependencies/base image and build a new digest |
| evaluation or policy gate | `evaluated` | reject it or fix source/policy and create a new candidate |
| artifact upload or transient runner error | last persisted state | rerun the same workflow run |
| staging approval denied | `approved` | leave pending or reject with the decision reason |
| staging deployment failure | `approved` or `failed` | retry the same digest after remediation |
| production approval denied | `staged` | keep staging evidence; do not rebuild |
| production deployment failure | `staged` or `failed` | stop rollout and retain the known-good production digest |

## Safe rerun

Use GitHub's **Re-run failed jobs** action on the original workflow run. The run ID remains stable,
so candidate and promotion idempotency keys remain stable. Confirm the rerun returns the same
release ID and provenance hash. If AgentHub reports an idempotency conflict, stop: the request no
longer matches the original immutable lineage.

Never change a manifest, evaluation report, SBOM, policy decision, or digest under an existing
retry key. A changed input is a new candidate.

## Resume a promotion

Read the current release and use its exact `state_revision` as `expected_revision`. Apply only the
next legal transition. For example, an approved release may enter staging, while an evaluated
release cannot jump directly to production. A stale revision returns a conflict; fetch state again
before deciding whether the intended transition already happened.

Protected-environment approval is separate from the control-plane transition. Verify both the
GitHub deployment approval and the append-only AgentHub event before announcing completion.

## Reject or mark failed

Use `rejected` when evidence or an operator decision makes the candidate unsuitable. Use `failed`
when an operational attempt failed and a policy-compliant retry may still be possible. Include a
specific reason, actor, expected revision, and new idempotency key. Do not delete release or event
records.

## Escalation record

Capture the workflow URL, release ID, source SHA, digest, failed gate reasons, last state and
revision, approver decision, remediation owner, and whether the stable production digest changed.
If production traffic was affected, continue with the incident workflow introduced in the later
incident-operations phase; until then, retain the previous known-good digest and stop promotion.
