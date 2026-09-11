"""Append-only persistence for sanitized governance events."""

from threading import Lock
from typing import Protocol

from sqlalchemy import select

from packages.contracts.governance import (
    GovernanceAuditEvent,
    GovernanceAuditOutcome,
)
from packages.governance.models import GovernanceAuditEventRecord
from packages.registry.database import Database


class GovernanceAuditStore(Protocol):
    """Persistence boundary shared by runtime enforcement and operator APIs."""

    def append(self, event: GovernanceAuditEvent) -> None: ...

    def list_events(
        self,
        *,
        agent_name: str | None = None,
        outcome: GovernanceAuditOutcome | None = None,
        limit: int = 100,
    ) -> list[GovernanceAuditEvent]: ...


class GovernanceAuditRepository:
    """PostgreSQL governance audit repository."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def append(self, event: GovernanceAuditEvent) -> None:
        with self._database.transaction() as session:
            session.add(
                GovernanceAuditEventRecord(
                    id=event.id,
                    event_type=event.event_type.value,
                    outcome=event.outcome.value,
                    allowed=event.allowed,
                    identity=event.identity,
                    agent_name=event.agent_name,
                    agent_version=event.agent_version,
                    action_kind=event.action_kind,
                    target=event.target,
                    policy_bundle_version=event.policy_bundle_version,
                    reasons=list(event.reasons),
                    obligations=event.obligations.model_dump(mode="json"),
                    occurred_at=event.occurred_at,
                    correlation_id=event.correlation_id,
                    release_id=event.release_id,
                    sanitized_input=event.sanitized_input.model_dump(mode="json"),
                )
            )

    def list_events(
        self,
        *,
        agent_name: str | None = None,
        outcome: GovernanceAuditOutcome | None = None,
        limit: int = 100,
    ) -> list[GovernanceAuditEvent]:
        with self._database.transaction() as session:
            statement = select(GovernanceAuditEventRecord)
            if agent_name is not None:
                statement = statement.where(GovernanceAuditEventRecord.agent_name == agent_name)
            if outcome is not None:
                statement = statement.where(GovernanceAuditEventRecord.outcome == outcome.value)
            records = session.execute(
                statement.order_by(
                    GovernanceAuditEventRecord.occurred_at.desc(),
                    GovernanceAuditEventRecord.id.desc(),
                ).limit(limit)
            ).scalars()
            return [self._view(record) for record in records]

    @staticmethod
    def _view(record: GovernanceAuditEventRecord) -> GovernanceAuditEvent:
        return GovernanceAuditEvent.model_validate(
            {
                "id": record.id,
                "event_type": record.event_type,
                "outcome": record.outcome,
                "allowed": record.allowed,
                "identity": record.identity,
                "agent_name": record.agent_name,
                "agent_version": record.agent_version,
                "action_kind": record.action_kind,
                "target": record.target,
                "policy_bundle_version": record.policy_bundle_version,
                "reasons": record.reasons,
                "obligations": record.obligations,
                "occurred_at": record.occurred_at,
                "correlation_id": record.correlation_id,
                "release_id": record.release_id,
                "sanitized_input": record.sanitized_input,
            }
        )


class InMemoryGovernanceAuditStore:
    """Thread-safe local/test audit store with the same query behavior."""

    def __init__(self) -> None:
        self._events: list[GovernanceAuditEvent] = []
        self._lock = Lock()

    def append(self, event: GovernanceAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_events(
        self,
        *,
        agent_name: str | None = None,
        outcome: GovernanceAuditOutcome | None = None,
        limit: int = 100,
    ) -> list[GovernanceAuditEvent]:
        with self._lock:
            events = [
                event
                for event in reversed(self._events)
                if (agent_name is None or event.agent_name == agent_name)
                and (outcome is None or event.outcome == outcome)
            ]
            return events[:limit]
