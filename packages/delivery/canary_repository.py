"""Transactional canary orchestration coupled atomically to traffic routes."""

import hashlib
import json
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CanaryEvent,
    CanaryGateDecision,
    CanaryProgress,
    CanaryResult,
    CanaryRollout,
    CanaryState,
    CreateCanaryRequest,
    RouteTarget,
    ShadowComparison,
    TrafficAllocation,
)
from packages.delivery.canary import CanaryStateMachine, InvalidCanaryTransition
from packages.delivery.guardrails import CanaryGuardrailEvaluator
from packages.delivery.models import (
    CanaryEventRecord,
    CanaryRolloutRecord,
    TrafficRouteEventRecord,
    TrafficRouteRecord,
)
from packages.delivery.repository import (
    DeliveryBlockedError,
    DeliveryConflictError,
    DeliveryNotFoundError,
)
from packages.registry.database import Database
from packages.registry.models import utc_now
from packages.release.models import ReleaseRecord


class CanaryStore(Protocol):
    def create(self, request: CreateCanaryRequest) -> CanaryResult: ...

    def get(self, rollout_id: UUID) -> CanaryRollout: ...

    def list_rollouts(self, route_id: UUID | None = None) -> list[CanaryRollout]: ...

    def transition(self, rollout_id: UUID, request: CanaryActionRequest) -> CanaryRollout: ...

    def events(self, rollout_id: UUID) -> list[CanaryEvent]: ...


class CanaryRepository:
    """Persist lifecycle and route changes within the same database transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, request: CreateCanaryRequest) -> CanaryResult:
        fingerprint = self._fingerprint(request)
        try:
            with self._database.transaction() as session:
                replay = session.execute(
                    select(CanaryRolloutRecord).where(
                        CanaryRolloutRecord.create_idempotency_key == request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if replay.create_fingerprint != fingerprint:
                        raise DeliveryConflictError(
                            "Canary retry token was already used for a different rollout"
                        )
                    return CanaryResult(created=False, rollout=self._view(session, replay))
                route = session.execute(
                    select(TrafficRouteRecord)
                    .where(TrafficRouteRecord.id == request.route_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if route is None:
                    raise DeliveryNotFoundError("Traffic route was not found")
                if route.revision != request.expected_route_revision:
                    raise DeliveryConflictError(
                        f"Route revision conflict: expected {request.expected_route_revision}, "
                        f"current is {route.revision}"
                    )
                if route.candidate_release_id is None:
                    raise DeliveryBlockedError("A canary requires a candidate release")
                if route.candidate_weight_basis_points != 0:
                    raise DeliveryBlockedError("A new canary must begin at zero candidate traffic")

                rollout_id = uuid4()
                occurred_at = utc_now()
                inserted = session.execute(
                    insert(CanaryRolloutRecord)
                    .values(
                        id=rollout_id,
                        route_id=route.id,
                        stable_release_id=route.stable_release_id,
                        candidate_release_id=route.candidate_release_id,
                        state=CanaryState.PENDING.value,
                        resume_state=None,
                        revision=1,
                        latest_gate=None,
                        create_idempotency_key=request.idempotency_key,
                        create_fingerprint=fingerprint,
                        created_by=request.actor,
                        created_at=occurred_at,
                        updated_by=request.actor,
                        updated_at=occurred_at,
                    )
                    .on_conflict_do_nothing()
                    .returning(CanaryRolloutRecord.id)
                ).scalar_one_or_none()
                if inserted is None:
                    existing = (
                        session.execute(
                            select(CanaryRolloutRecord).where(
                                or_(
                                    CanaryRolloutRecord.create_idempotency_key
                                    == request.idempotency_key,
                                    (CanaryRolloutRecord.route_id == route.id)
                                    & (
                                        CanaryRolloutRecord.candidate_release_id
                                        == route.candidate_release_id
                                    ),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    match = next(
                        (record for record in existing if record.create_fingerprint == fingerprint),
                        None,
                    )
                    if match is None:
                        raise DeliveryConflictError(
                            "Canary retry conflicts with an existing rollout or idempotency token"
                        )
                    return CanaryResult(created=False, rollout=self._view(session, match))

                progress = CanaryProgress()
                session.add(
                    CanaryEventRecord(
                        id=uuid4(),
                        rollout_id=rollout_id,
                        event_type="canary_created",
                        action=None,
                        actor=request.actor,
                        reason=request.reason,
                        idempotency_key=request.idempotency_key,
                        fingerprint=fingerprint,
                        previous_progress=None,
                        new_progress=progress.model_dump(mode="json"),
                        previous_revision=None,
                        new_revision=1,
                        previous_route_revision=route.revision,
                        new_route_revision=route.revision,
                        gate=None,
                        occurred_at=occurred_at,
                    )
                )
                session.flush()
                return CanaryResult(
                    created=True,
                    rollout=self._view(session, self._find(session, rollout_id)),
                )
        except IntegrityError as exc:
            raise DeliveryConflictError("Canary conflicts with persisted delivery state") from exc

    def get(self, rollout_id: UUID) -> CanaryRollout:
        with self._database.transaction() as session:
            return self._view(session, self._find(session, rollout_id))

    def list_rollouts(self, route_id: UUID | None = None) -> list[CanaryRollout]:
        with self._database.transaction() as session:
            statement = select(CanaryRolloutRecord)
            if route_id is not None:
                statement = statement.where(CanaryRolloutRecord.route_id == route_id)
            records = session.execute(
                statement.order_by(CanaryRolloutRecord.created_at.desc())
            ).scalars()
            return [self._view(session, record) for record in records]

    def transition(self, rollout_id: UUID, request: CanaryActionRequest) -> CanaryRollout:
        fingerprint = self._fingerprint(request)
        try:
            with self._database.transaction() as session:
                replay = session.execute(
                    select(CanaryEventRecord).where(
                        CanaryEventRecord.idempotency_key == request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if replay.rollout_id != rollout_id or replay.fingerprint != fingerprint:
                        raise DeliveryConflictError(
                            "Canary retry token was already used for a different action"
                        )
                    return self._view(session, self._find(session, rollout_id))

                rollout = session.execute(
                    select(CanaryRolloutRecord)
                    .where(CanaryRolloutRecord.id == rollout_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if rollout is None:
                    raise DeliveryNotFoundError("Canary rollout was not found")
                route = session.execute(
                    select(TrafficRouteRecord)
                    .where(TrafficRouteRecord.id == rollout.route_id)
                    .with_for_update()
                ).scalar_one()

                # A matching action can finish while this transaction waits for
                # the rollout lock. Recheck after both delivery rows are locked so
                # simultaneous retries return the already committed result.
                replay = session.execute(
                    select(CanaryEventRecord).where(
                        CanaryEventRecord.idempotency_key == request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if replay.rollout_id != rollout_id or replay.fingerprint != fingerprint:
                        raise DeliveryConflictError(
                            "Canary retry token was already used for a different action"
                        )
                    return self._view(session, rollout)

                if rollout.revision != request.expected_revision:
                    raise DeliveryConflictError(
                        f"Canary revision conflict: expected {request.expected_revision}, "
                        f"current is {rollout.revision}"
                    )
                if route.revision != request.expected_route_revision:
                    raise DeliveryConflictError(
                        f"Route revision conflict: expected {request.expected_route_revision}, "
                        f"current is {route.revision}"
                    )
                if (
                    route.stable_release_id != rollout.stable_release_id
                    or route.candidate_release_id != rollout.candidate_release_id
                ):
                    raise DeliveryConflictError(
                        "Traffic route lineage changed outside the active canary"
                    )

                current = self._progress(rollout)
                gate = self._gate(request, rollout, route)
                if (
                    request.action in {CanaryAction.START, CanaryAction.PROMOTE}
                    and not gate.allowed
                ):
                    raise DeliveryBlockedError("; ".join(gate.reasons))
                try:
                    updated = CanaryStateMachine.transition(current, request.action)
                except InvalidCanaryTransition as exc:
                    raise DeliveryConflictError(str(exc)) from exc

                occurred_at = utc_now()
                previous_revision = rollout.revision
                previous_route_revision = route.revision
                previous_allocation = self._allocation(session, route)
                route_changed = self._apply_route(
                    route, rollout, updated, request.actor, occurred_at
                )
                new_allocation = self._allocation(session, route)

                rollout.state = updated.state.value
                rollout.resume_state = (
                    updated.resume_state.value if updated.resume_state is not None else None
                )
                rollout.revision += 1
                rollout.latest_gate = (
                    gate.model_dump(mode="json")
                    if request.action in {CanaryAction.START, CanaryAction.PROMOTE}
                    else rollout.latest_gate
                )
                rollout.updated_by = request.actor
                rollout.updated_at = occurred_at
                if route_changed:
                    session.add(
                        TrafficRouteEventRecord(
                            id=uuid4(),
                            route_id=route.id,
                            event_type=f"canary_{request.action.value}",
                            actor=request.actor,
                            reason=request.reason,
                            idempotency_key=request.idempotency_key,
                            fingerprint=fingerprint,
                            previous_revision=previous_route_revision,
                            new_revision=route.revision,
                            previous_allocation=previous_allocation.model_dump(mode="json"),
                            new_allocation=new_allocation.model_dump(mode="json"),
                            occurred_at=occurred_at,
                        )
                    )
                session.add(
                    CanaryEventRecord(
                        id=uuid4(),
                        rollout_id=rollout.id,
                        event_type="canary_action",
                        action=request.action.value,
                        actor=request.actor,
                        reason=request.reason,
                        idempotency_key=request.idempotency_key,
                        fingerprint=fingerprint,
                        previous_progress=current.model_dump(mode="json"),
                        new_progress=updated.model_dump(mode="json"),
                        previous_revision=previous_revision,
                        new_revision=rollout.revision,
                        previous_route_revision=previous_route_revision,
                        new_route_revision=route.revision,
                        gate=(
                            gate.model_dump(mode="json")
                            if request.action in {CanaryAction.START, CanaryAction.PROMOTE}
                            else None
                        ),
                        occurred_at=occurred_at,
                    )
                )
                session.flush()
                return self._view(session, rollout)
        except IntegrityError as exc:
            raise DeliveryConflictError("Canary conflicts with persisted delivery state") from exc

    def events(self, rollout_id: UUID) -> list[CanaryEvent]:
        with self._database.transaction() as session:
            self._find(session, rollout_id)
            records = session.execute(
                select(CanaryEventRecord)
                .where(CanaryEventRecord.rollout_id == rollout_id)
                .order_by(CanaryEventRecord.occurred_at, CanaryEventRecord.id)
            ).scalars()
            return [self._event(record) for record in records]

    @staticmethod
    def _fingerprint(request: CreateCanaryRequest | CanaryActionRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _find(session: Session, rollout_id: UUID) -> CanaryRolloutRecord:
        record = session.get(CanaryRolloutRecord, rollout_id)
        if record is None:
            raise DeliveryNotFoundError("Canary rollout was not found")
        return record

    @staticmethod
    def _progress(record: CanaryRolloutRecord) -> CanaryProgress:
        return CanaryProgress(
            state=CanaryState(record.state),
            resume_state=CanaryState(record.resume_state) if record.resume_state else None,
        )

    @staticmethod
    def _gate(
        request: CanaryActionRequest,
        rollout: CanaryRolloutRecord,
        route: TrafficRouteRecord,
    ) -> CanaryGateDecision:
        comparison = request.comparison
        if request.action in {CanaryAction.START, CanaryAction.PROMOTE}:
            CanaryRepository._validate_comparison(comparison, rollout, route)
        return CanaryGuardrailEvaluator.evaluate(
            comparison,
            request.guardrail_policy,
            evaluated_at=utc_now(),
            telemetry_healthy=request.telemetry_healthy,
        )

    @staticmethod
    def _validate_comparison(
        comparison: ShadowComparison | None,
        rollout: CanaryRolloutRecord,
        route: TrafficRouteRecord,
    ) -> None:
        if comparison is None:
            return
        if (
            comparison.route_id != route.id
            or comparison.stable_release_id != rollout.stable_release_id
            or comparison.candidate_release_id != rollout.candidate_release_id
            or route.revision not in comparison.route_revisions
        ):
            raise DeliveryBlockedError(
                "Canary evidence does not match the current route revision and release pair"
            )

    @staticmethod
    def _apply_route(
        route: TrafficRouteRecord,
        rollout: CanaryRolloutRecord,
        progress: CanaryProgress,
        actor: str,
        occurred_at: datetime,
    ) -> bool:
        if progress.state in {CanaryState.PAUSED}:
            return False
        stable_id = route.stable_release_id
        candidate_id = route.candidate_release_id
        weight = CanaryStateMachine.weight_basis_points(progress)
        if progress.state is CanaryState.COMPLETED:
            stable_id = rollout.candidate_release_id
            candidate_id = None
            weight = 0
        if (
            stable_id == route.stable_release_id
            and candidate_id == route.candidate_release_id
            and weight == route.candidate_weight_basis_points
        ):
            return False
        route.stable_release_id = stable_id
        route.candidate_release_id = candidate_id
        route.candidate_weight_basis_points = weight
        route.revision += 1
        route.updated_by = actor
        route.updated_at = occurred_at
        return True

    @staticmethod
    def _release(session: Session, release_id: UUID) -> ReleaseRecord:
        record = session.get(ReleaseRecord, release_id)
        if record is None:  # pragma: no cover - protected by foreign keys
            raise DeliveryNotFoundError("Referenced release was not found")
        return record

    @classmethod
    def _target(cls, session: Session, release_id: UUID) -> RouteTarget:
        record = cls._release(session, release_id)
        return RouteTarget(
            release_id=record.id,
            agent_version_id=record.agent_version_id,
            agent_version=record.agent_version,
            provenance_hash=record.provenance_hash,
        )

    @classmethod
    def _allocation(cls, session: Session, route: TrafficRouteRecord) -> TrafficAllocation:
        return TrafficAllocation(
            stable=cls._target(session, route.stable_release_id),
            candidate=(
                cls._target(session, route.candidate_release_id)
                if route.candidate_release_id is not None
                else None
            ),
            candidate_weight_basis_points=route.candidate_weight_basis_points,
        )

    @classmethod
    def _view(cls, session: Session, record: CanaryRolloutRecord) -> CanaryRollout:
        route = session.get(TrafficRouteRecord, record.route_id)
        if route is None:  # pragma: no cover - protected by foreign keys
            raise DeliveryNotFoundError("Traffic route was not found")
        return CanaryRollout(
            id=record.id,
            route_id=record.route_id,
            stable_release_id=record.stable_release_id,
            candidate_release_id=record.candidate_release_id,
            progress=cls._progress(record),
            revision=record.revision,
            route_revision=route.revision,
            latest_gate=(
                CanaryGateDecision.model_validate(record.latest_gate)
                if record.latest_gate is not None
                else None
            ),
            created_by=record.created_by,
            created_at=record.created_at,
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _event(record: CanaryEventRecord) -> CanaryEvent:
        return CanaryEvent(
            id=record.id,
            rollout_id=record.rollout_id,
            event_type=record.event_type,
            action=CanaryAction(record.action) if record.action else None,
            actor=record.actor,
            reason=record.reason,
            idempotency_key=record.idempotency_key,
            previous_progress=(
                CanaryProgress.model_validate(record.previous_progress)
                if record.previous_progress is not None
                else None
            ),
            new_progress=CanaryProgress.model_validate(record.new_progress),
            previous_revision=record.previous_revision,
            new_revision=record.new_revision,
            previous_route_revision=record.previous_route_revision,
            new_route_revision=record.new_route_revision,
            gate=(
                CanaryGateDecision.model_validate(record.gate) if record.gate is not None else None
            ),
            occurred_at=record.occurred_at,
        )
