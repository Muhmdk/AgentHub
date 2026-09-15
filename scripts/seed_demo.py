"""Reset and seed the safe local AgentHub walkthrough state."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import make_url

from agents.shared.providers import create_database, create_provider_bundle
from apps.api.config import Settings, load_settings
from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CreateCanaryRequest,
    CreateTrafficRouteRequest,
    DeliveryEnvironment,
    MetricDelta,
    ShadowComparison,
)
from packages.contracts.evaluation import RunEvaluationRequest
from packages.contracts.governance import ToolAccess
from packages.contracts.incident import ObserveIncidentSignalRequest
from packages.contracts.manifest import AgentManifest
from packages.contracts.release import (
    CreateCandidateRequest,
    PolicyAttestation,
    PromoteReleaseRequest,
    ReleaseState,
    SecurityAttestation,
)
from packages.contracts.runtime import AgentErrorCode, AgentExecutionError
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.evaluation.__main__ import create_targets
from packages.evaluation.repository import EvaluationRepository
from packages.evaluation.service import EvaluationService
from packages.governance import (
    GovernanceAuditRepository,
    LocalPolicyEngine,
    PolicyAuthorizer,
    agent_policy_profiles,
)
from packages.incidents.evidence_repository import IncidentEvidenceRepository
from packages.incidents.faults import TopKRegressionFault
from packages.incidents.repository import IncidentRepository
from packages.incidents.service import IncidentService
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository
from packages.registry.schema import EXPECTED_SCHEMA_REVISION
from packages.release.repository import ReleaseRepository
from packages.release.service import ReleaseService

ROOT = Path(__file__).parents[1]

_DEMO_TABLES = (
    "rollback_events",
    "rollback_operations",
    "incident_evidence",
    "incident_triggers",
    "incidents",
    "canary_events",
    "canary_rollouts",
    "traffic_route_events",
    "traffic_routes",
    "release_events",
    "releases",
    "governance_audit_events",
    "evaluation_gate_decisions",
    "evaluation_metrics",
    "evaluation_case_results",
    "evaluation_runs",
    "registry_audit_events",
    "agent_versions",
    "agents",
)


@dataclass(frozen=True)
class DemoSeedReport:
    """Identifiers needed to follow the seeded walkthrough."""

    fixture_notice: str
    registered_agents: int
    passing_evaluation_id: str
    failing_evaluation_id: str
    stable_release_id: str
    candidate_release_id: str
    route_id: str
    canary_rollout_id: str
    incident_id: str
    governance_denial_recorded: bool


def require_safe_demo_database(settings: Settings, database: Database) -> None:
    """Fail closed unless a reset points at the documented local demo database."""
    url = make_url(database.engine.url.render_as_string(hide_password=False))
    if (
        settings.environment not in {"local", "test"}
        or settings.model_provider != "fake"
        or settings.retrieval_provider != "local"
        or url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "agenthub"
    ):
        raise RuntimeError(
            "Demo reset is restricted to the local agenthub PostgreSQL database "
            "with deterministic local providers in local or test mode"
        )
    if database.schema_revision() != EXPECTED_SCHEMA_REVISION:
        raise RuntimeError("Demo reset requires the current database migration revision")


def reset_demo(settings: Settings, database: Database) -> None:
    """Remove only known AgentHub application tables after the safety check."""
    require_safe_demo_database(settings, database)
    with database.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(_DEMO_TABLES)} CASCADE"))


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _metric(
    delta: float,
    *,
    unit: Literal["score", "milliseconds", "rate", "usd"] = "score",
    lower_is_better: bool = False,
) -> MetricDelta:
    return MetricDelta(
        samples=100,
        stable_mean=0.8,
        candidate_mean=0.8 + delta,
        delta=delta,
        confidence_low=delta,
        confidence_high=delta,
        unit=unit,
        lower_is_better=lower_is_better,
    )


def _healthy_comparison(
    *,
    route_id: UUID,
    route_revision: int,
    stable_release_id: UUID,
    candidate_release_id: UUID,
    observed_at: datetime,
) -> ShadowComparison:
    return ShadowComparison(
        route_id=route_id,
        route_revisions=[route_revision],
        stable_release_id=stable_release_id,
        candidate_release_id=candidate_release_id,
        sample_count=100,
        successful_sample_count=100,
        window_start=observed_at - timedelta(minutes=10),
        window_end=observed_at - timedelta(seconds=5),
        quality=_metric(0.01),
        safety=_metric(0.01),
        latency=_metric(10, unit="milliseconds", lower_is_better=True),
        error_rate=_metric(0, unit="rate", lower_is_better=True),
        cost=_metric(0.001, unit="usd", lower_is_better=True),
    )


def _candidate_request(evaluation_id: UUID, label: str) -> CreateCandidateRequest:
    return CreateCandidateRequest(
        idempotency_key=f"demo-{label}-candidate",
        agent_name="knowledge-agent",
        agent_version="1.0.0",
        evaluation_run_id=evaluation_id,
        sbom_digest=_digest(f"synthetic-demo-{label}-sbom"),
        build_provenance_digest=_digest(f"synthetic-demo-{label}-provenance"),
        security=SecurityAttestation(
            dependency_scan_passed=True,
            image_scan_passed=True,
            maximum_severity="none",
            scanner="synthetic-demo-fixture",
            scanner_version="1.0.0",
        ),
        policy=PolicyAttestation(
            decision_id="demo-fixture-policy",
            decision_version="1.0.0",
            passed=True,
            reasons=["synthetic_demo_evidence_only"],
        ),
        actor="demo-seed",
    )


def _promote(
    service: ReleaseService,
    release_id: UUID,
    states: tuple[ReleaseState, ...],
    label: str,
) -> None:
    for revision, state in enumerate(states, start=1):
        service.promote(
            release_id,
            PromoteReleaseRequest(
                target_state=state,
                actor="demo-seed",
                reason=f"Synthetic demo {label} transition to {state.value}",
                expected_revision=revision,
                idempotency_key=f"demo-{label}-{state.value}",
            ),
        )


async def seed_demo(
    settings: Settings,
    database: Database,
    *,
    model_name: str = "fake/deterministic-v1",
) -> DemoSeedReport:
    """Build one coherent synthetic walkthrough through production services."""
    registry = RegistryRepository(database)
    for manifest_path in sorted((ROOT / "data" / "manifests").glob("*.json")):
        registry.register(
            AgentManifest.model_validate_json(manifest_path.read_text(encoding="utf-8")),
            actor="demo-seed",
            correlation_id=f"demo-register-{manifest_path.stem}",
        )

    evaluations = EvaluationRepository(database)
    evaluation_service = EvaluationService(
        registry=registry,
        store=evaluations,
        targets=create_targets(),
    )
    passing = await evaluation_service.run(
        RunEvaluationRequest(
            agent_name="inventory-agent",
            agent_version="1.0.0",
            suite_id="inventory-agent-suite",
            candidate_profile="default",
            environment="local-demo",
        )
    )
    failing = await evaluation_service.run(
        RunEvaluationRequest(
            agent_name="inventory-agent",
            agent_version="1.0.0",
            suite_id="inventory-agent-suite",
            candidate_profile="regressed",
            baseline_run_id=passing.run_id,
            environment="local-demo",
        )
    )
    delivery_evaluation = await evaluation_service.run(
        RunEvaluationRequest(
            agent_name="knowledge-agent",
            agent_version="1.0.0",
            suite_id="knowledge-agent-suite",
            candidate_profile="default",
            environment="local-demo",
        )
    )
    if not passing.gate.passed or failing.gate.passed or not delivery_evaluation.gate.passed:
        raise RuntimeError("Synthetic demo evaluations did not produce the expected gates")

    releases = ReleaseRepository(database)
    release_service = ReleaseService(registry, evaluations, releases)
    stable = release_service.create_candidate(
        _candidate_request(delivery_evaluation.run_id, "stable")
    ).release
    candidate = release_service.create_candidate(
        _candidate_request(delivery_evaluation.run_id, "candidate")
    ).release
    _promote(
        release_service,
        stable.id,
        (ReleaseState.APPROVED, ReleaseState.STAGED, ReleaseState.PRODUCTION),
        "stable",
    )
    _promote(
        release_service,
        candidate.id,
        (ReleaseState.APPROVED, ReleaseState.STAGED),
        "candidate",
    )

    routes = DeliveryRepository(database)
    route = routes.create(
        CreateTrafficRouteRequest(
            idempotency_key="demo-production-route",
            agent_name="knowledge-agent",
            environment=DeliveryEnvironment.PRODUCTION,
            stable_release_id=stable.id,
            candidate_release_id=candidate.id,
            candidate_weight_basis_points=0,
            actor="demo-seed",
            reason="Synthetic demo shadow candidate route",
        )
    ).route
    canaries = CanaryRepository(database)
    canary = canaries.create(
        CreateCanaryRequest(
            idempotency_key="demo-canary-create",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="demo-seed",
            reason="Synthetic demo five-percent canary",
        )
    ).rollout
    observed_at = datetime.now(UTC)
    canary = canaries.transition(
        canary.id,
        CanaryActionRequest(
            idempotency_key="demo-canary-start",
            action=CanaryAction.START,
            expected_revision=canary.revision,
            expected_route_revision=route.revision,
            actor="demo-seed",
            reason="Synthetic paired evidence passed the five-percent gate",
            comparison=_healthy_comparison(
                route_id=route.id,
                route_revision=route.revision,
                stable_release_id=stable.id,
                candidate_release_id=candidate.id,
                observed_at=observed_at,
            ),
            telemetry_healthy=True,
        ),
    )
    route = routes.get(route.id)

    scenario = TopKRegressionFault().build(
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        release_id=candidate.id,
        route_id=route.id,
        canary_rollout_id=canary.id,
        observed_at=observed_at,
    )
    incidents = IncidentRepository(database)
    detection = IncidentService(incidents).observe(
        request=ObserveIncidentSignalRequest(signal=scenario.signal, actor="demo-seed")
    )
    if detection.result is None:
        raise RuntimeError("Synthetic incident was not detected")
    incident = detection.result.incident
    IncidentEvidenceRepository(database).collect(
        incident.id,
        list(scenario.evidence),
        actor="demo-seed",
    )

    authorizer = PolicyAuthorizer(
        LocalPolicyEngine(),
        agent_policy_profiles(model_name)["knowledge-agent"],
        settings.environment,
        GovernanceAuditRepository(database),
    )
    denial_recorded = False
    try:
        await authorizer.authorize_tool(
            tool_name="admin.delete",
            required_scopes=["admin:write"],
            access=ToolAccess.WRITE,
            arguments={"resource": "synthetic-demo"},
        )
    except AgentExecutionError as exc:
        denial_recorded = exc.code is AgentErrorCode.POLICY_DENIED
    if not denial_recorded:
        raise RuntimeError("Synthetic governance denial was not recorded")

    return DemoSeedReport(
        fixture_notice="Synthetic local demo evidence; not production observations or attestations",
        registered_agents=len(registry.list_agents()),
        passing_evaluation_id=str(passing.run_id),
        failing_evaluation_id=str(failing.run_id),
        stable_release_id=str(stable.id),
        candidate_release_id=str(candidate.id),
        route_id=str(route.id),
        canary_rollout_id=str(canary.id),
        incident_id=str(incident.id),
        governance_denial_recorded=denial_recorded,
    )


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--reset",
        action="store_true",
        help="clear known local application tables before seeding",
    )
    return command


def main(arguments: list[str] | None = None) -> int:
    parsed = parser().parse_args(arguments)
    settings = load_settings()
    providers = create_provider_bundle(settings)
    database = create_database(settings, providers)
    try:
        require_safe_demo_database(settings, database)
        if parsed.reset:
            reset_demo(settings, database)
        report = asyncio.run(seed_demo(settings, database, model_name=providers.model.name))
    finally:
        database.dispose()
        providers.close()
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
