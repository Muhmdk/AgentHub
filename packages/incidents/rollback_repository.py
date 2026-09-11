"""Durable rollback reservations, bounded attempts, and append-only audit events."""

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.contracts.incident import (
    RollbackCommand,
    RollbackMode,
    RollbackOperation,
    RollbackPolicyDecision,
    RollbackReservation,
    RollbackStatus,
)
from packages.incidents.models import RollbackEventRecord, RollbackOperationRecord
from packages.registry.database import Database
from packages.registry.models import utc_now


class RollbackConflictError(RuntimeError):
    """A rollback token, active operation, or status conflicts with persisted state."""


class RollbackOperationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def find_by_key(self, idempotency_key: str) -> RollbackOperation | None:
        with self._database.transaction() as session:
            record = session.execute(
                select(RollbackOperationRecord).where(
                    RollbackOperationRecord.idempotency_key == idempotency_key
                )
            ).scalar_one_or_none()
            return self._view(record) if record is not None else None

    def attempts(self, incident_id: UUID) -> tuple[int, datetime | None]:
        with self._database.transaction() as session:
            count = session.execute(
                select(func.count())
                .select_from(RollbackOperationRecord)
                .where(RollbackOperationRecord.incident_id == incident_id)
            ).scalar_one()
            latest = session.execute(
                select(RollbackOperationRecord.updated_at)
                .where(RollbackOperationRecord.incident_id == incident_id)
                .order_by(RollbackOperationRecord.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return int(count), latest

    def reserve(
        self, command: RollbackCommand, decision: RollbackPolicyDecision
    ) -> RollbackReservation:
        if not decision.allowed:
            raise ValueError("Denied rollback decisions cannot be reserved")
        fingerprint = self._fingerprint(command, decision)
        try:
            with self._database.transaction() as session:
                replay = session.execute(
                    select(RollbackOperationRecord).where(
                        RollbackOperationRecord.idempotency_key == command.request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    return self._replay(replay, command, fingerprint)
                attempt = session.execute(
                    select(func.count())
                    .select_from(RollbackOperationRecord)
                    .where(RollbackOperationRecord.incident_id == command.request.incident_id)
                ).scalar_one()
                now = utc_now()
                record = RollbackOperationRecord(
                    id=uuid4(),
                    incident_id=command.request.incident_id,
                    route_id=command.request.route_id,
                    canary_rollout_id=command.request.canary_rollout_id,
                    target_release_id=command.request.target_release_id,
                    target_provenance_hash=command.request.target_provenance_hash,
                    command_hash=command.command_hash,
                    mode=(
                        RollbackMode.AUTOMATIC if decision.automatic else RollbackMode.MANUAL
                    ).value,
                    status=RollbackStatus.REQUESTED.value,
                    attempt_number=int(attempt) + 1,
                    decision=decision.model_dump(mode="json"),
                    idempotency_key=command.request.idempotency_key,
                    fingerprint=fingerprint,
                    actor=command.request.actor,
                    reason=command.request.reason,
                    route_revision_before=command.request.expected_route_revision,
                    route_revision_after=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
                session.flush()
                session.add(
                    RollbackEventRecord(
                        id=uuid4(),
                        operation_id=record.id,
                        status=RollbackStatus.REQUESTED.value,
                        reason="Rollback command reserved after policy evaluation",
                        occurred_at=now,
                    )
                )
                session.flush()
                return RollbackReservation(created=True, operation=self._view(record))
        except IntegrityError as exc:
            existing = self.find_by_key(command.request.idempotency_key)
            if existing is not None and existing.command_hash == command.command_hash:
                return RollbackReservation(created=False, operation=existing)
            raise RollbackConflictError(
                "Rollback conflicts with an active or persisted operation"
            ) from exc

    def complete(self, operation_id: UUID, route_revision: int) -> RollbackOperation:
        return self._transition(
            operation_id,
            RollbackStatus.EXECUTED,
            "Known-good route allocation was executed",
            route_revision=route_revision,
        )

    def fail(self, operation_id: UUID) -> RollbackOperation:
        return self._transition(
            operation_id,
            RollbackStatus.FAILED,
            "Rollback execution failed before recovery verification",
        )

    def _transition(
        self,
        operation_id: UUID,
        status: RollbackStatus,
        reason: str,
        *,
        route_revision: int | None = None,
    ) -> RollbackOperation:
        with self._database.transaction() as session:
            record = session.execute(
                select(RollbackOperationRecord)
                .where(RollbackOperationRecord.id == operation_id)
                .with_for_update()
            ).scalar_one_or_none()
            if record is None:
                raise RollbackConflictError("Rollback operation was not found")
            if record.status == status.value:
                return self._view(record)
            if record.status != RollbackStatus.REQUESTED.value:
                raise RollbackConflictError("Rollback operation is not awaiting execution")
            now = utc_now()
            record.status = status.value
            record.route_revision_after = route_revision
            record.updated_at = now
            session.add(
                RollbackEventRecord(
                    id=uuid4(),
                    operation_id=record.id,
                    status=status.value,
                    reason=reason,
                    occurred_at=now,
                )
            )
            session.flush()
            return self._view(record)

    @staticmethod
    def _replay(
        record: RollbackOperationRecord, command: RollbackCommand, fingerprint: str
    ) -> RollbackReservation:
        if record.command_hash != command.command_hash or record.fingerprint != fingerprint:
            raise RollbackConflictError(
                "Rollback retry token was already used for a different command"
            )
        return RollbackReservation(
            created=False, operation=RollbackOperationRepository._view(record)
        )

    @staticmethod
    def _fingerprint(command: RollbackCommand, decision: RollbackPolicyDecision) -> str:
        canonical = json.dumps(
            {
                "command": command.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _view(record: RollbackOperationRecord) -> RollbackOperation:
        return RollbackOperation(
            id=record.id,
            incident_id=record.incident_id,
            route_id=record.route_id,
            canary_rollout_id=record.canary_rollout_id,
            target_release_id=record.target_release_id,
            target_provenance_hash=record.target_provenance_hash,
            command_hash=record.command_hash,
            mode=record.mode,
            status=record.status,
            attempt_number=record.attempt_number,
            decision=record.decision,
            idempotency_key=record.idempotency_key,
            actor=record.actor,
            reason=record.reason,
            route_revision_before=record.route_revision_before,
            route_revision_after=record.route_revision_after,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
