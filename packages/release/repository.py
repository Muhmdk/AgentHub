"""Transactional, idempotent release and promotion persistence."""

from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.release import (
    CandidateResult,
    PromoteReleaseRequest,
    ReleaseEventView,
    ReleaseState,
    ReleaseView,
)
from packages.registry.database import Database
from packages.registry.models import utc_now
from packages.release.lifecycle import can_transition, transition_reason
from packages.release.models import ReleaseEventRecord, ReleaseRecord


class ReleaseNotFoundError(RuntimeError):
    """Requested release does not exist."""


class ReleaseConflictError(RuntimeError):
    """Release identity, state, or retry token conflicts with persisted state."""


class ReleaseBlockedError(RuntimeError):
    """A technical or policy gate prevents promotion."""


class ReleaseStore(Protocol):
    def create(self, release: ReleaseView, fingerprint: str) -> CandidateResult: ...

    def get(self, release_id: UUID) -> ReleaseView: ...

    def list_releases(self, agent_name: str | None = None) -> list[ReleaseView]: ...

    def transition(self, release_id: UUID, change: PromoteReleaseRequest) -> ReleaseView: ...

    def events(self, release_id: UUID) -> list[ReleaseEventView]: ...


class ReleaseRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, release: ReleaseView, fingerprint: str) -> CandidateResult:
        try:
            with self._database.transaction() as session:
                inserted = session.execute(
                    insert(ReleaseRecord)
                    .values(
                        id=release.id,
                        agent_version_id=release.agent_version_id,
                        evaluation_run_id=release.provenance.evaluation_run_id,
                        agent_name=release.agent_name,
                        agent_version=release.agent_version,
                        state=release.state.value,
                        state_revision=release.state_revision,
                        idempotency_key=release.idempotency_key,
                        fingerprint=fingerprint,
                        provenance_hash=release.provenance_hash,
                        provenance=release.provenance.model_dump(mode="json"),
                        security=release.security.model_dump(mode="json"),
                        policy=release.policy.model_dump(mode="json"),
                        gate=release.gate.model_dump(mode="json"),
                        created_by=release.created_by,
                        created_at=release.created_at,
                        updated_at=release.updated_at,
                    )
                    .on_conflict_do_nothing()
                    .returning(ReleaseRecord.id)
                ).scalar_one_or_none()
                if inserted is None:
                    existing = (
                        session.execute(
                            select(ReleaseRecord).where(
                                or_(
                                    ReleaseRecord.idempotency_key == release.idempotency_key,
                                    ReleaseRecord.provenance_hash == release.provenance_hash,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    match = next(
                        (record for record in existing if record.fingerprint == fingerprint), None
                    )
                    if match is None:
                        raise ReleaseConflictError(
                            "Candidate retry conflicts with immutable release lineage"
                        )
                    return CandidateResult(created=False, release=self._view(match))

                session.add(
                    ReleaseEventRecord(
                        id=uuid4(),
                        release_id=release.id,
                        event_type="candidate_created",
                        actor=release.created_by,
                        occurred_at=release.created_at,
                        previous_state=None,
                        new_state=release.state.value,
                        idempotency_key=release.idempotency_key,
                        reason="Candidate attestations attached",
                        provenance_hash=release.provenance_hash,
                    )
                )
                session.flush()
                return CandidateResult(created=True, release=release)
        except IntegrityError as exc:
            raise ReleaseConflictError("Candidate violates immutable release storage") from exc

    def get(self, release_id: UUID) -> ReleaseView:
        with self._database.transaction() as session:
            return self._view(self._find(session, release_id))

    def list_releases(self, agent_name: str | None = None) -> list[ReleaseView]:
        with self._database.transaction() as session:
            statement = select(ReleaseRecord)
            if agent_name is not None:
                statement = statement.where(ReleaseRecord.agent_name == agent_name)
            records = session.execute(statement.order_by(ReleaseRecord.created_at.desc())).scalars()
            return [self._view(record) for record in records]

    def transition(self, release_id: UUID, change: PromoteReleaseRequest) -> ReleaseView:
        try:
            with self._database.transaction() as session:
                replay = session.execute(
                    select(ReleaseEventRecord).where(
                        ReleaseEventRecord.idempotency_key == change.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if (
                        replay.release_id != release_id
                        or replay.new_state != change.target_state.value
                    ):
                        raise ReleaseConflictError(
                            "Promotion retry token was already used for a different transition"
                        )
                    return self._view(self._find(session, release_id))

                record = session.execute(
                    select(ReleaseRecord).where(ReleaseRecord.id == release_id).with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    raise ReleaseNotFoundError("Release was not found")
                if record.state_revision != change.expected_revision:
                    raise ReleaseConflictError(
                        f"State revision conflict: expected {change.expected_revision}, "
                        f"current is {record.state_revision}"
                    )
                current = ReleaseState(record.state)
                view = self._view(record)
                if not can_transition(current, change.target_state, view.gate):
                    reason = transition_reason(current, change.target_state, view.gate)
                    if not view.gate.passed and change.target_state in {
                        ReleaseState.APPROVED,
                        ReleaseState.STAGED,
                        ReleaseState.PRODUCTION,
                    }:
                        raise ReleaseBlockedError(reason)
                    raise ReleaseConflictError(reason)

                occurred_at = utc_now()
                record.state = change.target_state.value
                record.state_revision += 1
                record.updated_at = occurred_at
                session.add(
                    ReleaseEventRecord(
                        id=uuid4(),
                        release_id=release_id,
                        event_type="release_transition",
                        actor=change.actor,
                        occurred_at=occurred_at,
                        previous_state=current.value,
                        new_state=change.target_state.value,
                        idempotency_key=change.idempotency_key,
                        reason=change.reason,
                        provenance_hash=record.provenance_hash,
                    )
                )
                session.flush()
                return self._view(record)
        except IntegrityError as exc:
            raise ReleaseConflictError("Promotion conflicts with persisted release state") from exc

    def events(self, release_id: UUID) -> list[ReleaseEventView]:
        with self._database.transaction() as session:
            self._find(session, release_id)
            records = session.execute(
                select(ReleaseEventRecord)
                .where(ReleaseEventRecord.release_id == release_id)
                .order_by(ReleaseEventRecord.occurred_at, ReleaseEventRecord.id)
            ).scalars()
            return [
                ReleaseEventView(
                    id=record.id,
                    release_id=record.release_id,
                    event_type=record.event_type,
                    actor=record.actor,
                    occurred_at=record.occurred_at,
                    previous_state=(
                        ReleaseState(record.previous_state) if record.previous_state else None
                    ),
                    new_state=ReleaseState(record.new_state),
                    idempotency_key=record.idempotency_key,
                    reason=record.reason,
                    provenance_hash=record.provenance_hash,
                )
                for record in records
            ]

    @staticmethod
    def _find(session: Session, release_id: UUID) -> ReleaseRecord:
        record = session.get(ReleaseRecord, release_id)
        if record is None:
            raise ReleaseNotFoundError("Release was not found")
        return record

    @staticmethod
    def _view(record: ReleaseRecord) -> ReleaseView:
        return ReleaseView(
            id=record.id,
            agent_version_id=record.agent_version_id,
            agent_name=record.agent_name,
            agent_version=record.agent_version,
            state=ReleaseState(record.state),
            state_revision=record.state_revision,
            idempotency_key=record.idempotency_key,
            provenance=record.provenance,
            provenance_hash=record.provenance_hash,
            security=record.security,
            policy=record.policy,
            gate=record.gate,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
