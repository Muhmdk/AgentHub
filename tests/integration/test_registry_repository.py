"""PostgreSQL integration coverage for immutable, concurrent registry behavior."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from apps.api.config import load_settings
from packages.contracts.manifest import AgentManifest
from packages.contracts.registry import LifecycleState
from packages.registry.bootstrap import main as bootstrap_main
from packages.registry.database import Database
from packages.registry.repository import RegistryConflictError, RegistryRepository

ROOT = Path(__file__).parents[2]


def load_manifest(name: str = "inventory") -> AgentManifest:
    path = ROOT / "data" / "manifests" / f"{name}-agent-v1.json"
    return AgentManifest.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_empty_database_migration_created_registry_schema(
    registry_database: Database,
) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())

    assert {"alembic_version", "agents", "agent_versions", "registry_audit_events"} <= tables


@pytest.mark.integration
def test_registration_is_idempotent_and_conflicting_version_is_rejected(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    manifest = load_manifest()

    first = repository.register(manifest, actor="ci-user", correlation_id="registration-1")
    repeated = repository.register(manifest, actor="ci-user", correlation_id="registration-2")
    changed_manifest = manifest.model_copy(
        update={
            "spec": manifest.spec.model_copy(
                update={"source": manifest.spec.source.model_copy(update={"commit_sha": "b" * 40})}
            )
        }
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.agent_version.id == first.agent_version.id
    with pytest.raises(RegistryConflictError, match="different manifest"):
        repository.register(
            changed_manifest, actor="ci-user", correlation_id="registration-conflict"
        )
    assert len(repository.list_audit_events("inventory-agent", "1.0.0")) == 1


@pytest.mark.integration
def test_concurrent_identical_registration_creates_one_version_and_event(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    manifest = load_manifest("knowledge")

    def register(index: int) -> tuple[bool, str]:
        result = repository.register(
            manifest,
            actor="concurrency-test",
            correlation_id=f"concurrent-{index}",
        )
        return result.created, str(result.agent_version.id)

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(register, range(8)))

    assert sum(created for created, _ in outcomes) == 1
    assert len({version_id for _, version_id in outcomes}) == 1
    assert len(repository.list_audit_events("knowledge-agent", "1.0.0")) == 1


@pytest.mark.integration
def test_versions_are_immutable_but_lifecycle_fields_can_change(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    registered = repository.register(
        load_manifest(), actor="ci-user", correlation_id="immutability"
    )

    with (
        pytest.raises(DBAPIError, match="metadata is immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE agent_versions SET source_sha = :sha WHERE id = :id"),
            {"sha": "c" * 40, "id": registered.agent_version.id},
        )

    transitioned = repository.transition(
        "inventory-agent",
        "1.0.0",
        target=LifecycleState.REGISTERED,
        actor="release-manager",
        reason="Manifest review complete",
        expected_revision=1,
        correlation_id="transition-1",
    )
    assert transitioned.lifecycle_state == LifecycleState.REGISTERED
    assert transitioned.state_revision == 2
    assert (
        transitioned.manifest.spec.source.commit_sha == "a88fb630a9e5aa377feee41fbb542be66ddba2ac"
    )


@pytest.mark.integration
def test_illegal_and_stale_transitions_return_conflicts_with_reasons(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    repository.register(load_manifest(), actor="ci-user", correlation_id="transition-setup")

    with pytest.raises(RegistryConflictError, match="draft to production is not permitted"):
        repository.transition(
            "inventory-agent",
            "1.0.0",
            target=LifecycleState.PRODUCTION,
            actor="release-manager",
            reason=None,
            expected_revision=1,
            correlation_id="illegal-transition",
        )
    repository.transition(
        "inventory-agent",
        "1.0.0",
        target=LifecycleState.REGISTERED,
        actor="release-manager",
        reason=None,
        expected_revision=1,
        correlation_id="legal-transition",
    )
    with pytest.raises(RegistryConflictError, match="expected 1, current is 2"):
        repository.transition(
            "inventory-agent",
            "1.0.0",
            target=LifecycleState.EVALUATING,
            actor="stale-client",
            reason=None,
            expected_revision=1,
            correlation_id="stale-transition",
        )


@pytest.mark.integration
def test_audit_event_records_transition_context_and_is_append_only(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    result = repository.register(
        load_manifest("shopping"), actor="manifest-loader", correlation_id="audit-register"
    )
    repository.transition(
        "shopping-agent",
        "1.0.0",
        target=LifecycleState.REGISTERED,
        actor="release-manager",
        reason="Ownership confirmed",
        expected_revision=1,
        correlation_id="audit-transition",
    )

    events = repository.list_audit_events("shopping-agent", "1.0.0")
    assert [event.event_type for event in events] == ["registered", "lifecycle_transition"]
    transition = events[1]
    assert transition.actor == "release-manager"
    assert transition.previous_state == LifecycleState.DRAFT
    assert transition.new_state == LifecycleState.REGISTERED
    assert transition.correlation_id == "audit-transition"
    assert transition.manifest_hash == result.agent_version.manifest_hash
    assert transition.details == {"reason": "Ownership confirmed"}

    with (
        pytest.raises(DBAPIError, match="append-only"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE registry_audit_events SET actor = 'tampered' WHERE id = :id"),
            {"id": transition.id},
        )


@pytest.mark.integration
def test_all_demo_manifests_populate_inventory_and_version_history(
    registry_database: Database,
) -> None:
    repository = RegistryRepository(registry_database)
    for name in ("inventory", "knowledge", "shopping"):
        repository.register(
            load_manifest(name), actor="bootstrap", correlation_id=f"bootstrap-{name}"
        )

    summaries = repository.list_agents()
    assert [summary.name for summary in summaries] == [
        "inventory-agent",
        "knowledge-agent",
        "shopping-agent",
    ]
    assert {summary.owner for summary in summaries} == {"retail-ai-team"}
    shopping_versions = repository.list_versions("shopping-agent")
    assert len(shopping_versions) == 1
    assert shopping_versions[0].manifest.spec.tools[0].name == "product.search"
    assert json.loads(shopping_versions[0].model_dump_json())["lifecycle_state"] == "draft"


@pytest.mark.integration
def test_manifest_bootstrap_command_is_idempotent(
    registry_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "AGENTHUB_DATABASE_URL",
        registry_database.engine.url.render_as_string(hide_password=False),
    )
    load_settings.cache_clear()
    try:
        assert bootstrap_main() == 0
        first = json.loads(capsys.readouterr().out)
        assert bootstrap_main() == 0
        repeated = json.loads(capsys.readouterr().out)
    finally:
        load_settings.cache_clear()

    assert first["manifest_count"] == 3
    assert first["created_count"] == 3
    assert repeated["created_count"] == 0
