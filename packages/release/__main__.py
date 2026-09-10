"""Create candidates, promote releases, and simulate the release pipeline."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

from apps.api.config import load_settings
from packages.contracts.evaluation import EvaluationRunReport, RunEvaluationRequest
from packages.contracts.release import (
    CreateCandidateRequest,
    PolicyAttestation,
    PromoteReleaseRequest,
    ReleaseState,
    SecurityAttestation,
)
from packages.evaluation.__main__ import create_targets, ensure_registered
from packages.evaluation.repository import EvaluationRepository
from packages.evaluation.service import EvaluationService
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository
from packages.release.repository import ReleaseBlockedError, ReleaseRepository
from packages.release.service import ReleaseService


def _boolean(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Operate the AgentHub release pipeline")
    subcommands = command.add_subparsers(dest="command", required=True)

    candidate = subcommands.add_parser("candidate", help="Attach evidence to a candidate")
    candidate.add_argument("--evaluation-report", required=True, type=Path)
    candidate.add_argument("--sbom", required=True, type=Path)
    candidate.add_argument("--build-provenance", required=True, type=Path)
    candidate.add_argument("--idempotency-key", required=True)
    candidate.add_argument("--actor", default="release-workflow")
    candidate.add_argument("--dependency-scan-passed", type=_boolean, default=True)
    candidate.add_argument("--image-scan-passed", type=_boolean, default=True)
    candidate.add_argument(
        "--maximum-severity",
        choices=("none", "low", "medium", "high", "critical"),
        default="none",
    )
    candidate.add_argument("--scanner", default="trivy")
    candidate.add_argument("--scanner-version", default="workflow-pinned-sha")
    candidate.add_argument("--policy-passed", type=_boolean, default=True)
    candidate.add_argument("--policy-reason", action="append", default=[])

    promote = subcommands.add_parser("promote", help="Apply one guarded state transition")
    promote.add_argument("--release-id", required=True, type=UUID)
    promote.add_argument(
        "--target-state",
        required=True,
        choices=("approved", "staged", "production", "rejected", "failed"),
    )
    promote.add_argument("--expected-revision", required=True, type=int)
    promote.add_argument("--idempotency-key", required=True)
    promote.add_argument("--actor", default="release-workflow")
    promote.add_argument("--reason", required=True)

    simulate = subcommands.add_parser("simulate", help="Run a local candidate pipeline")
    simulate.add_argument("--agent", default="inventory-agent")
    simulate.add_argument("--version", default="1.0.0")
    simulate.add_argument(
        "--candidate-profile", choices=("default", "regressed"), default="default"
    )
    simulate.add_argument("--security-passed", type=_boolean, default=True)
    simulate.add_argument("--policy-passed", type=_boolean, default=True)
    simulate.add_argument("--pipeline-id", default="local-release-simulation")
    return command


def _service(database: Database) -> ReleaseService:
    return ReleaseService(
        RegistryRepository(database),
        EvaluationRepository(database),
        ReleaseRepository(database),
    )


def _candidate_request(
    arguments: argparse.Namespace,
    report: EvaluationRunReport,
) -> CreateCandidateRequest:
    reasons = arguments.policy_reason if arguments.policy_reason else []
    return CreateCandidateRequest(
        idempotency_key=arguments.idempotency_key,
        agent_name=report.agent_name,
        agent_version=report.agent_version,
        evaluation_run_id=report.run_id,
        sbom_digest=_digest(arguments.sbom),
        build_provenance_digest=_digest(arguments.build_provenance),
        security=SecurityAttestation(
            dependency_scan_passed=arguments.dependency_scan_passed,
            image_scan_passed=arguments.image_scan_passed,
            maximum_severity=arguments.maximum_severity,
            scanner=arguments.scanner,
            scanner_version=arguments.scanner_version,
        ),
        policy=PolicyAttestation(
            decision_id="release-policy",
            decision_version="1.0.0",
            passed=arguments.policy_passed,
            reasons=reasons,
        ),
        actor=arguments.actor,
    )


def create_candidate(
    arguments: argparse.Namespace, database: Database
) -> tuple[dict[str, object], int]:
    report = EvaluationRunReport.model_validate_json(
        arguments.evaluation_report.read_text(encoding="utf-8")
    )
    EvaluationRepository(database).save(report)
    result = _service(database).create_candidate(_candidate_request(arguments, report))
    payload = result.model_dump(mode="json")
    return payload, 0 if result.release.gate.passed else 2


def promote(arguments: argparse.Namespace, database: Database) -> tuple[dict[str, object], int]:
    release = _service(database).promote(
        arguments.release_id,
        PromoteReleaseRequest(
            target_state=ReleaseState(arguments.target_state),
            actor=arguments.actor,
            reason=arguments.reason,
            expected_revision=arguments.expected_revision,
            idempotency_key=arguments.idempotency_key,
        ),
    )
    return release.model_dump(mode="json"), 0


async def simulate(
    arguments: argparse.Namespace, database: Database
) -> tuple[dict[str, object], int]:
    registry = RegistryRepository(database)
    evaluations = EvaluationRepository(database)
    ensure_registered(registry, arguments.agent, arguments.version)
    report = await EvaluationService(
        registry=registry,
        store=evaluations,
        targets=create_targets(),
    ).run(
        RunEvaluationRequest(
            agent_name=arguments.agent,
            agent_version=arguments.version,
            suite_id=f"{arguments.agent}-suite",
            candidate_profile=arguments.candidate_profile,
            environment="local",
        )
    )
    evidence = f"sha256:{hashlib.sha256(arguments.pipeline_id.encode()).hexdigest()}"
    request = CreateCandidateRequest(
        idempotency_key=arguments.pipeline_id,
        agent_name=report.agent_name,
        agent_version=report.agent_version,
        evaluation_run_id=report.run_id,
        sbom_digest=evidence,
        build_provenance_digest=evidence,
        security=SecurityAttestation(
            dependency_scan_passed=arguments.security_passed,
            image_scan_passed=arguments.security_passed,
            maximum_severity="none" if arguments.security_passed else "high",
            scanner="local-simulation",
            scanner_version="1.0.0",
        ),
        policy=PolicyAttestation(
            decision_id="release-policy",
            decision_version="1.0.0",
            passed=arguments.policy_passed,
            reasons=[] if arguments.policy_passed else ["policy denied local simulation"],
        ),
        actor="local-release-simulation",
    )
    service = _service(database)
    first = service.create_candidate(request)
    replay = service.create_candidate(request)
    release = first.release
    blocked_reason = None
    approved_change: PromoteReleaseRequest | None = None
    promotion_replay_preserved_state = False
    try:
        for revision, target in enumerate(
            (ReleaseState.APPROVED, ReleaseState.STAGED, ReleaseState.PRODUCTION), start=1
        ):
            change = PromoteReleaseRequest(
                target_state=target,
                actor="local-release-simulation",
                reason=f"Local {target.value} gate completed",
                expected_revision=revision,
                idempotency_key=f"{arguments.pipeline_id}-{target.value}",
            )
            if target == ReleaseState.APPROVED:
                approved_change = change
            release = service.promote(release.id, change)
        if approved_change is not None:
            promotion_replay = service.promote(release.id, approved_change)
            promotion_replay_preserved_state = promotion_replay == release
    except ReleaseBlockedError as exc:
        blocked_reason = str(exc)

    events = ReleaseRepository(database).events(release.id)
    payload: dict[str, object] = {
        "status": "promoted" if release.state == ReleaseState.PRODUCTION else "blocked",
        "release": release.model_dump(mode="json"),
        "evaluation": report.model_dump(mode="json"),
        "idempotency": {
            "candidate_created_once": first.created and not replay.created,
            "same_release_on_retry": first.release.id == replay.release.id,
            "promotion_replay_preserved_state": promotion_replay_preserved_state,
            "event_count": len(events),
        },
        "blocked_reason": blocked_reason,
    }
    return payload, 0 if release.state == ReleaseState.PRODUCTION else 2


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    settings = load_settings()
    database = Database(settings.database_url)
    try:
        if arguments.command == "candidate":
            payload, status = create_candidate(arguments, database)
        elif arguments.command == "promote":
            payload, status = promote(arguments, database)
        else:
            payload, status = asyncio.run(simulate(arguments, database))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 1
    finally:
        database.dispose()
    print(json.dumps(payload, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
