"""PostgreSQL governance audit durability and immutability tests."""

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agents.shared.model import DeterministicFakeModel
from packages.contracts.governance import GovernanceAuditOutcome, PolicyInput
from packages.contracts.runtime import ChatMessage, ModelRequest
from packages.governance import (
    AuthorizedChatModel,
    GovernanceAuditRepository,
    LocalPolicyEngine,
    PolicyAuthorizer,
    agent_policy_profiles,
)
from packages.registry.database import Database


@pytest.fixture
def governance_database(migrated_database: Database) -> Iterator[Database]:
    with migrated_database.engine.begin() as connection:
        connection.execute(text("TRUNCATE governance_audit_events"))
    yield migrated_database
    with migrated_database.engine.begin() as connection:
        connection.execute(text("TRUNCATE governance_audit_events"))


@pytest.mark.integration
def test_governance_events_survive_repository_instances_and_are_append_only(
    governance_database: Database,
) -> None:
    repository = GovernanceAuditRepository(governance_database)
    profile = agent_policy_profiles("fake/deterministic-v1")["inventory-agent"]
    model = AuthorizedChatModel(
        DeterministicFakeModel(),
        PolicyAuthorizer(LocalPolicyEngine(), profile, "test", repository),
    )
    asyncio.run(
        model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Secret prompt")]))
    )

    events = GovernanceAuditRepository(governance_database).list_events(
        outcome=GovernanceAuditOutcome.ALLOW
    )
    assert len(events) == 1
    event = events[0]
    assert isinstance(event.sanitized_input, PolicyInput)
    assert "Secret prompt" not in event.model_dump_json()

    with (
        pytest.raises(DBAPIError, match="append-only"),
        governance_database.engine.begin() as connection,
    ):
        connection.execute(
            text("UPDATE governance_audit_events SET allowed = false WHERE id = :id"),
            {"id": event.id},
        )

    with (
        pytest.raises(DBAPIError, match="append-only"),
        governance_database.engine.begin() as connection,
    ):
        connection.execute(
            text("DELETE FROM governance_audit_events WHERE id = :id"),
            {"id": event.id},
        )
