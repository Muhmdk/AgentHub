# Governance emergency procedure

Use this procedure only when the deployed policy service or current policy bundle prevents
security-critical AgentHub operation because of an outage or confirmed policy regression. It is
not a mechanism to override a legitimate deny, skip an approval, raise a budget, expose a direct
agent route, or make an unavailable audit database optional.

AgentHub has no fail-open or unaudited bypass switch. During recovery, denied traffic remains
denied. The only permitted emergency policy action is a time-bounded rollback to a previously
reviewed, immutable Helm release containing a known-good policy bundle.

## Preconditions

1. Open an incident record and assign an incident commander and a separate service owner.
2. Record the environment, start time, affected actions, correlation IDs, current application
   image digest, Helm revision, policy bundle version, and last known-good Helm revision.
3. Confirm whether the failure is gateway authentication, PostgreSQL audit persistence, OPA
   availability, or a policy decision. A legitimate deny is not an outage.
4. Freeze new registrations and promotions. Preserve the last known-good production release and
   do not change model, tool, identity, or database configuration.
5. Obtain two distinct human approvals through the protected production environment. Neither
   approver may be the operator executing the rollback.

If a last known-good immutable revision and two approvals do not exist, stop. Keep returning the
safe error, route users to an unaffected service if one exists, and escalate to the security owner.

## Recovery

Inspect history without changing the cluster:

```bash
helm history agenthub --namespace agenthub
kubectl get pods --namespace agenthub
kubectl logs --namespace agenthub deploy/agenthub -c policy --tail=200
```

Do not copy log output into an issue until it has been checked for identifiers. Select the exact
previously approved Helm revision from the incident record, then execute one bounded rollback:

```bash
helm rollback agenthub <KNOWN_GOOD_REVISION> \
  --namespace agenthub \
  --wait \
  --timeout 5m
```

Do not use `kubectl edit`, replace a ConfigMap by hand, disable the OPA sidecar, change the policy
URL, create a local production identity, delete audit rows, or expose a new Service/Ingress. If
the rollback times out or changes an unexpected image digest, stop and restore the prior Helm
revision; do not improvise a second control path.

## Verification

1. Confirm both API and policy containers are ready and the application image digest matches the
   approved incident record.
2. Invoke one expected allow and one expected deny through the authenticated gateway using a
   dedicated emergency verification identity and explicit correlation IDs.
3. Verify the allow reaches its read-only target, the deny returns `403`, and both appear in
   `/governance/audit` with the restored policy bundle version and verification identity.
4. Verify a request without gateway credentials returns `401` and the production direct agent
   route returns `404`.
5. Confirm new rate/budget enforcement events can be persisted. If audit storage is unavailable,
   the system must continue returning `503`; restore PostgreSQL rather than bypassing audit.
6. Attach sanitized command output, approvals, Helm revisions, correlation IDs, policy versions,
   and verification results to the incident record.

## Closure

End the emergency window after verification or 30 minutes, whichever comes first. If service is
not restored within 30 minutes, keep it failed closed and transfer control to the incident owner.
Unfreeze promotions only after security reviews the incident evidence.

Create a normal pull request for the policy correction, reproduce the regression with a Rego or
gateway test, and pass the complete CI suite. Record the permanent fix commit, review identities,
deployment run, final policy bundle version, and time the known-good release was superseded. Never
rewrite or delete the emergency audit trail.
