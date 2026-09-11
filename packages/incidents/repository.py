"""Transactional and idempotent incident intake persistence."""

import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.incident import (
    Incident,
    IncidentResult,
    IncidentSeverity,
    IncidentSignal,
    IncidentStatus,
    IncidentTrigger,
    TriggerEvaluation,
)
from packages.incidents.models import IncidentRecord, IncidentTriggerRecord
from packages.registry.database import Database
from packages.registry.models import utc_now


class IncidentNotFoundError(RuntimeError):
    """Requested incident does not exist."""


class IncidentConflictError(RuntimeError):
    """Incident identity or idempotency token conflicts with persisted state."""


class IncidentStore(Protocol):
    def create(
        self, signal: IncidentSignal, evaluation: TriggerEvaluation, actor: str
    ) -> IncidentResult: ...

    def get(self, incident_id: UUID) -> Incident: ...

    def list_incidents(self, agent_name: str | None = None) -> list[Incident]: ...

    def triggers(self, incident_id: UUID) -> list[IncidentTrigger]: ...


class IncidentRepository:
    """Persist an incident and its originating trigger in one transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self, signal: IncidentSignal, evaluation: TriggerEvaluation, actor: str
    ) -> IncidentResult:
        if not evaluation.breached:
            raise ValueError("Non-breaching signals cannot create incidents")
        fingerprint = self._fingerprint(signal, actor)
        try:
            return self._insert(signal, evaluation, actor, fingerprint)
        except IntegrityError:
            return self._replay(signal, fingerprint)

    def get(self, incident_id: UUID) -> Incident:
        with self._database.transaction() as session:
            return self._view(session, self._find(session, incident_id))

    def list_incidents(self, agent_name: str | None = None) -> list[Incident]:
        with self._database.transaction() as session:
            statement = select(IncidentRecord)
            if agent_name is not None:
                statement = statement.where(IncidentRecord.agent_name == agent_name)
            records = session.execute(
                statement.order_by(IncidentRecord.created_at.desc(), IncidentRecord.id)
            ).scalars()
            return [self._view(session, record) for record in records]

    def triggers(self, incident_id: UUID) -> list[IncidentTrigger]:
        with self._database.transaction() as session:
            self._find(session, incident_id)
            records = session.execute(
                select(IncidentTriggerRecord)
                .where(IncidentTriggerRecord.incident_id == incident_id)
                .order_by(IncidentTriggerRecord.occurred_at, IncidentTriggerRecord.id)
            ).scalars()
            return [self._trigger(record) for record in records]

    def _insert(
        self,
        signal: IncidentSignal,
        evaluation: TriggerEvaluation,
        actor: str,
        fingerprint: str,
    ) -> IncidentResult:
        with self._database.transaction() as session:
            replay = session.execute(
                select(IncidentRecord).where(
                    IncidentRecord.create_idempotency_key == signal.idempotency_key
                )
            ).scalar_one_or_none()
            if replay is not None:
                return self._validate_replay(session, replay, fingerprint)

            incident_id = uuid4()
            trigger_id = uuid4()
            recorded_at = utc_now()
            incident = IncidentRecord(
                id=incident_id,
                agent_name=signal.agent_name,
                environment=signal.environment.value,
                title=self._title(signal),
                status=IncidentStatus.DETECTED.value,
                severity=signal.severity.value,
                release_id=signal.release_id,
                route_id=signal.route_id,
                canary_rollout_id=signal.canary_rollout_id,
                revision=1,
                create_idempotency_key=signal.idempotency_key,
                create_fingerprint=fingerprint,
                created_by=actor,
                detected_at=signal.observed_at,
                created_at=recorded_at,
                updated_at=recorded_at,
            )
            trigger = IncidentTriggerRecord(
                id=trigger_id,
                incident_id=incident_id,
                trigger_type=signal.trigger_type.value,
                severity=signal.severity.value,
                signal_name=signal.signal_name,
                observed_value=signal.observed_value,
                threshold=signal.threshold,
                operator=evaluation.operator,
                source_ref=signal.source_ref,
                summary=signal.summary,
                release_id=signal.release_id,
                route_id=signal.route_id,
                canary_rollout_id=signal.canary_rollout_id,
                idempotency_key=signal.idempotency_key,
                fingerprint=fingerprint,
                occurred_at=signal.observed_at,
                recorded_at=recorded_at,
            )
            session.add_all((incident, trigger))
            session.flush()
            return IncidentResult(
                created=True,
                incident=self._view(session, incident),
                trigger=self._trigger(trigger),
            )

    def _replay(self, signal: IncidentSignal, fingerprint: str) -> IncidentResult:
        with self._database.transaction() as session:
            record = session.execute(
                select(IncidentRecord).where(
                    IncidentRecord.create_idempotency_key == signal.idempotency_key
                )
            ).scalar_one_or_none()
            if record is None:
                raise IncidentConflictError("Incident conflicts with persisted intake state")
            return self._validate_replay(session, record, fingerprint)

    def _validate_replay(
        self, session: Session, record: IncidentRecord, fingerprint: str
    ) -> IncidentResult:
        if record.create_fingerprint != fingerprint:
            raise IncidentConflictError(
                "Incident retry token was already used for a different operational signal"
            )
        trigger = session.execute(
            select(IncidentTriggerRecord).where(IncidentTriggerRecord.incident_id == record.id)
        ).scalar_one()
        return IncidentResult(
            created=False,
            incident=self._view(session, record),
            trigger=self._trigger(trigger),
        )

    @staticmethod
    def _fingerprint(signal: IncidentSignal, actor: str) -> str:
        canonical = json.dumps(
            {"actor": actor, "signal": signal.model_dump(mode="json")},
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _title(signal: IncidentSignal) -> str:
        kind = signal.trigger_type.value.replace("_", " ")
        return f"{signal.agent_name}: {kind} in {signal.environment.value}"

    @staticmethod
    def _find(session: Session, incident_id: UUID) -> IncidentRecord:
        record = session.get(IncidentRecord, incident_id)
        if record is None:
            raise IncidentNotFoundError("Incident was not found")
        return record

    @classmethod
    def _view(cls, session: Session, record: IncidentRecord) -> Incident:
        trigger_count = len(
            session.execute(
                select(IncidentTriggerRecord.id).where(
                    IncidentTriggerRecord.incident_id == record.id
                )
            )
            .scalars()
            .all()
        )
        return Incident(
            id=record.id,
            agent_name=record.agent_name,
            environment=record.environment,
            title=record.title,
            status=record.status,
            severity=record.severity,
            release_id=record.release_id,
            route_id=record.route_id,
            canary_rollout_id=record.canary_rollout_id,
            revision=record.revision,
            trigger_count=trigger_count,
            created_by=record.created_by,
            detected_at=record.detected_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _trigger(record: IncidentTriggerRecord) -> IncidentTrigger:
        return IncidentTrigger(
            id=record.id,
            incident_id=record.incident_id,
            trigger_type=record.trigger_type,
            severity=IncidentSeverity(record.severity),
            signal_name=record.signal_name,
            observed_value=record.observed_value,
            threshold=record.threshold,
            operator=record.operator,
            source_ref=record.source_ref,
            summary=record.summary,
            release_id=record.release_id,
            route_id=record.route_id,
            canary_rollout_id=record.canary_rollout_id,
            idempotency_key=record.idempotency_key,
            fingerprint=record.fingerprint,
            occurred_at=record.occurred_at,
            recorded_at=record.recorded_at,
        )
