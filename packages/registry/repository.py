"""Transactional PostgreSQL repository for agent registration and lifecycle."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from packages.contracts.manifest import AgentManifest, RiskTier
from packages.contracts.registry import (
    AgentSummary,
    AgentVersionView,
    AuditEventView,
    LifecycleState,
    RegistrationResult,
)
from packages.contracts.runtime import JsonValue
from packages.registry.database import Database
from packages.registry.lifecycle import can_transition, transition_reason
from packages.registry.models import AgentRecord, AgentVersionRecord, AuditEventRecord


class RegistryNotFoundError(RuntimeError):
    """Requested agent or version does not exist."""


class RegistryConflictError(RuntimeError):
    """Requested registration or state change conflicts with immutable registry state."""


class RegistryStore(Protocol):
    def register(
        self, manifest: AgentManifest, *, actor: str, correlation_id: str
    ) -> RegistrationResult: ...

    def list_agents(self) -> list[AgentSummary]: ...

    def get_agent(self, agent_name: str) -> AgentSummary: ...

    def list_versions(self, agent_name: str) -> list[AgentVersionView]: ...

    def get_version(self, agent_name: str, version: str) -> AgentVersionView: ...

    def transition(
        self,
        agent_name: str,
        version: str,
        *,
        target: LifecycleState,
        actor: str,
        reason: str | None,
        expected_revision: int,
        correlation_id: str,
    ) -> AgentVersionView: ...

    def list_audit_events(self, agent_name: str, version: str) -> list[AuditEventView]: ...


class RegistryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def register(
        self, manifest: AgentManifest, *, actor: str, correlation_id: str
    ) -> RegistrationResult:
        now = datetime.now(UTC)
        agent_id = uuid4()
        version_id = uuid4()
        with self._database.transaction() as session:
            inserted_agent_id = session.execute(
                insert(AgentRecord)
                .values(
                    id=agent_id,
                    name=manifest.metadata.name,
                    display_name=manifest.metadata.display_name,
                    owner=manifest.metadata.owner,
                    risk_tier=manifest.metadata.risk_tier.value,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["name"])
                .returning(AgentRecord.id)
            ).scalar_one_or_none()
            if inserted_agent_id is None:
                agent = session.execute(
                    select(AgentRecord).where(AgentRecord.name == manifest.metadata.name)
                ).scalar_one()
                agent_id = agent.id

            existing = self._find_version(session, agent_id, manifest.metadata.version)
            if existing is not None:
                if existing.manifest_hash != manifest.manifest_hash:
                    raise RegistryConflictError(
                        "Agent version already exists with a different manifest"
                    )
                return RegistrationResult(
                    created=False,
                    agent_version=self._version_view(existing),
                )

            inserted_version_id = session.execute(
                insert(AgentVersionRecord)
                .values(**self._version_values(version_id, agent_id, manifest, now))
                .on_conflict_do_nothing(index_elements=["agent_id", "version"])
                .returning(AgentVersionRecord.id)
            ).scalar_one_or_none()
            if inserted_version_id is None:
                concurrent = self._find_version(session, agent_id, manifest.metadata.version)
                if concurrent is None or concurrent.manifest_hash != manifest.manifest_hash:
                    raise RegistryConflictError(
                        "Agent version already exists with a different manifest"
                    )
                return RegistrationResult(
                    created=False,
                    agent_version=self._version_view(concurrent),
                )

            stored_agent = session.get(AgentRecord, agent_id)
            if stored_agent is None:  # pragma: no cover - protected by foreign key
                raise RegistryNotFoundError("Agent disappeared during registration")
            stored_agent.display_name = manifest.metadata.display_name
            stored_agent.owner = manifest.metadata.owner
            stored_agent.risk_tier = manifest.metadata.risk_tier.value
            stored_agent.updated_at = now

            record = session.get(AgentVersionRecord, inserted_version_id)
            if record is None:  # pragma: no cover - inserted in this transaction
                raise RegistryNotFoundError("Agent version disappeared during registration")
            session.add(
                AuditEventRecord(
                    id=uuid4(),
                    agent_version_id=record.id,
                    event_type="registered",
                    actor=actor,
                    occurred_at=now,
                    previous_state=None,
                    new_state=LifecycleState.DRAFT.value,
                    correlation_id=correlation_id,
                    manifest_hash=manifest.manifest_hash,
                    details={},
                )
            )
            session.flush()
            return RegistrationResult(created=True, agent_version=self._version_view(record))

    def list_agents(self) -> list[AgentSummary]:
        with self._database.transaction() as session:
            agents = session.execute(select(AgentRecord).order_by(AgentRecord.name)).scalars()
            return [self._agent_summary(session, agent) for agent in agents]

    def get_agent(self, agent_name: str) -> AgentSummary:
        with self._database.transaction() as session:
            return self._agent_summary(session, self._find_agent(session, agent_name))

    def list_versions(self, agent_name: str) -> list[AgentVersionView]:
        with self._database.transaction() as session:
            agent = self._find_agent(session, agent_name)
            records = session.execute(
                select(AgentVersionRecord)
                .where(AgentVersionRecord.agent_id == agent.id)
                .order_by(AgentVersionRecord.created_at.desc())
            ).scalars()
            return [self._version_view(record) for record in records]

    def get_version(self, agent_name: str, version: str) -> AgentVersionView:
        with self._database.transaction() as session:
            agent = self._find_agent(session, agent_name)
            record = self._find_version(session, agent.id, version)
            if record is None:
                raise RegistryNotFoundError("Agent version was not found")
            return self._version_view(record)

    def transition(
        self,
        agent_name: str,
        version: str,
        *,
        target: LifecycleState,
        actor: str,
        reason: str | None,
        expected_revision: int,
        correlation_id: str,
    ) -> AgentVersionView:
        with self._database.transaction() as session:
            agent = self._find_agent(session, agent_name)
            record = session.execute(
                self._version_query(agent.id, version).with_for_update()
            ).scalar_one_or_none()
            if record is None:
                raise RegistryNotFoundError("Agent version was not found")
            previous = LifecycleState(record.lifecycle_state)
            if record.state_revision != expected_revision:
                raise RegistryConflictError(
                    f"State revision conflict: expected {expected_revision}, "
                    f"current is {record.state_revision}"
                )
            if not can_transition(previous, target):
                raise RegistryConflictError(transition_reason(previous, target))

            record.lifecycle_state = target.value
            record.state_revision += 1
            occurred_at = datetime.now(UTC)
            session.add(
                AuditEventRecord(
                    id=uuid4(),
                    agent_version_id=record.id,
                    event_type="lifecycle_transition",
                    actor=actor,
                    occurred_at=occurred_at,
                    previous_state=previous.value,
                    new_state=target.value,
                    correlation_id=correlation_id,
                    manifest_hash=record.manifest_hash,
                    details={"reason": reason} if reason else {},
                )
            )
            session.flush()
            return self._version_view(record)

    def list_audit_events(self, agent_name: str, version: str) -> list[AuditEventView]:
        with self._database.transaction() as session:
            agent = self._find_agent(session, agent_name)
            record = self._find_version(session, agent.id, version)
            if record is None:
                raise RegistryNotFoundError("Agent version was not found")
            events = session.execute(
                select(AuditEventRecord)
                .where(AuditEventRecord.agent_version_id == record.id)
                .order_by(AuditEventRecord.occurred_at, AuditEventRecord.id)
            ).scalars()
            return [self._audit_view(event) for event in events]

    @staticmethod
    def _find_agent(session: Session, name: str) -> AgentRecord:
        agent = session.execute(
            select(AgentRecord).where(AgentRecord.name == name)
        ).scalar_one_or_none()
        if agent is None:
            raise RegistryNotFoundError("Agent was not found")
        return agent

    @staticmethod
    def _agent_summary(session: Session, agent: AgentRecord) -> AgentSummary:
        latest = session.execute(
            select(AgentVersionRecord)
            .where(AgentVersionRecord.agent_id == agent.id)
            .order_by(AgentVersionRecord.created_at.desc())
            .limit(1)
        ).scalar_one()
        return AgentSummary(
            id=agent.id,
            name=agent.name,
            display_name=agent.display_name,
            owner=agent.owner,
            risk_tier=RiskTier(agent.risk_tier),
            latest_version=latest.version,
            lifecycle_state=LifecycleState(latest.lifecycle_state),
            created_at=agent.created_at,
        )

    @classmethod
    def _find_version(
        cls, session: Session, agent_id: UUID, version: str
    ) -> AgentVersionRecord | None:
        return session.execute(cls._version_query(agent_id, version)).scalar_one_or_none()

    @staticmethod
    def _version_query(agent_id: UUID, version: str) -> Select[tuple[AgentVersionRecord]]:
        return select(AgentVersionRecord).where(
            AgentVersionRecord.agent_id == agent_id,
            AgentVersionRecord.version == version,
        )

    @staticmethod
    def _version_values(
        version_id: UUID,
        agent_id: UUID,
        manifest: AgentManifest,
        created_at: datetime,
    ) -> dict[str, object]:
        retrieval: dict[str, JsonValue] | None = None
        if manifest.spec.retrieval is not None:
            retrieval = manifest.spec.retrieval.model_dump(mode="json")
        return {
            "id": version_id,
            "agent_id": agent_id,
            "version": manifest.metadata.version,
            "schema_version": manifest.schema_version,
            "manifest_hash": manifest.manifest_hash,
            "manifest": manifest.model_dump(mode="json"),
            "source_repository": manifest.spec.source.repository,
            "source_sha": manifest.spec.source.commit_sha,
            "image_reference": manifest.spec.runtime.image,
            "prompt_id": manifest.spec.prompt.prompt_id,
            "prompt_version": manifest.spec.prompt.version,
            "model_provider": manifest.spec.model.provider,
            "model_name": manifest.spec.model.name,
            "model_config": manifest.spec.model.parameters,
            "tool_specs": [tool.model_dump(mode="json") for tool in manifest.spec.tools],
            "retrieval_config": retrieval,
            "lifecycle_state": LifecycleState.DRAFT.value,
            "state_revision": 1,
            "created_at": created_at,
        }

    @staticmethod
    def _version_view(record: AgentVersionRecord) -> AgentVersionView:
        return AgentVersionView(
            id=record.id,
            agent_id=record.agent_id,
            version=record.version,
            manifest_hash=record.manifest_hash,
            manifest=AgentManifest.model_validate(record.manifest),
            lifecycle_state=LifecycleState(record.lifecycle_state),
            state_revision=record.state_revision,
            created_at=record.created_at,
        )

    @staticmethod
    def _audit_view(record: AuditEventRecord) -> AuditEventView:
        return AuditEventView(
            id=record.id,
            agent_version_id=record.agent_version_id,
            event_type=record.event_type,
            actor=record.actor,
            occurred_at=record.occurred_at,
            previous_state=(
                LifecycleState(record.previous_state) if record.previous_state else None
            ),
            new_state=LifecycleState(record.new_state),
            correlation_id=record.correlation_id,
            manifest_hash=record.manifest_hash,
            details=record.details,
        )
