"""Transactional persistence for atomic stable and candidate traffic routes."""

import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.delivery import (
    CreateTrafficRouteRequest,
    DeliveryEnvironment,
    ReplaceTrafficRouteRequest,
    RouteTarget,
    TrafficAllocation,
    TrafficRoute,
    TrafficRouteEvent,
    TrafficRouteResult,
)
from packages.contracts.release import ReleaseState
from packages.delivery.models import TrafficRouteEventRecord, TrafficRouteRecord
from packages.registry.database import Database
from packages.registry.models import utc_now
from packages.release.models import ReleaseRecord


class DeliveryNotFoundError(RuntimeError):
    """Requested route or release does not exist."""


class DeliveryConflictError(RuntimeError):
    """A route revision, identity, or idempotency token conflicts."""


class DeliveryBlockedError(RuntimeError):
    """A release is not eligible to receive traffic."""


class DeliveryStore(Protocol):
    def create(self, request: CreateTrafficRouteRequest) -> TrafficRouteResult: ...

    def get(self, route_id: UUID) -> TrafficRoute: ...

    def get_for_agent(self, agent_name: str, environment: DeliveryEnvironment) -> TrafficRoute: ...

    def list_routes(self, agent_name: str | None = None) -> list[TrafficRoute]: ...

    def replace(self, route_id: UUID, request: ReplaceTrafficRouteRequest) -> TrafficRoute: ...

    def events(self, route_id: UUID) -> list[TrafficRouteEvent]: ...


class DeliveryRepository:
    """Store complete route snapshots with transactional compare-and-swap updates."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, request: CreateTrafficRouteRequest) -> TrafficRouteResult:
        fingerprint = self._fingerprint(request)
        try:
            with self._database.transaction() as session:
                allocation = self._validated_allocation(
                    session,
                    agent_name=request.agent_name,
                    environment=request.environment,
                    stable_release_id=request.stable_release_id,
                    candidate_release_id=request.candidate_release_id,
                    candidate_weight_basis_points=request.candidate_weight_basis_points,
                )
                route_id = uuid4()
                occurred_at = utc_now()
                inserted = session.execute(
                    insert(TrafficRouteRecord)
                    .values(
                        id=route_id,
                        agent_name=request.agent_name,
                        environment=request.environment.value,
                        stable_release_id=request.stable_release_id,
                        candidate_release_id=request.candidate_release_id,
                        candidate_weight_basis_points=request.candidate_weight_basis_points,
                        revision=1,
                        create_idempotency_key=request.idempotency_key,
                        create_fingerprint=fingerprint,
                        created_by=request.actor,
                        created_at=occurred_at,
                        updated_by=request.actor,
                        updated_at=occurred_at,
                    )
                    .on_conflict_do_nothing()
                    .returning(TrafficRouteRecord.id)
                ).scalar_one_or_none()
                if inserted is None:
                    existing = (
                        session.execute(
                            select(TrafficRouteRecord).where(
                                or_(
                                    TrafficRouteRecord.create_idempotency_key
                                    == request.idempotency_key,
                                    (TrafficRouteRecord.agent_name == request.agent_name)
                                    & (TrafficRouteRecord.environment == request.environment.value),
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
                            "Route retry conflicts with an existing route or idempotency token"
                        )
                    return TrafficRouteResult(created=False, route=self._view(session, match))

                session.add(
                    TrafficRouteEventRecord(
                        id=uuid4(),
                        route_id=route_id,
                        event_type="route_created",
                        actor=request.actor,
                        reason=request.reason,
                        idempotency_key=request.idempotency_key,
                        fingerprint=fingerprint,
                        previous_revision=None,
                        new_revision=1,
                        previous_allocation=None,
                        new_allocation=allocation.model_dump(mode="json"),
                        occurred_at=occurred_at,
                    )
                )
                session.flush()
                record = self._find(session, route_id)
                return TrafficRouteResult(created=True, route=self._view(session, record))
        except IntegrityError as exc:
            raise DeliveryConflictError("Route conflicts with persisted delivery state") from exc

    def get(self, route_id: UUID) -> TrafficRoute:
        with self._database.transaction() as session:
            return self._view(session, self._find(session, route_id))

    def get_for_agent(self, agent_name: str, environment: DeliveryEnvironment) -> TrafficRoute:
        with self._database.transaction() as session:
            record = session.execute(
                select(TrafficRouteRecord).where(
                    TrafficRouteRecord.agent_name == agent_name,
                    TrafficRouteRecord.environment == environment.value,
                )
            ).scalar_one_or_none()
            if record is None:
                raise DeliveryNotFoundError("Traffic route was not found")
            return self._view(session, record)

    def list_routes(self, agent_name: str | None = None) -> list[TrafficRoute]:
        with self._database.transaction() as session:
            statement = select(TrafficRouteRecord)
            if agent_name is not None:
                statement = statement.where(TrafficRouteRecord.agent_name == agent_name)
            records = session.execute(
                statement.order_by(
                    TrafficRouteRecord.agent_name,
                    TrafficRouteRecord.environment,
                )
            ).scalars()
            return [self._view(session, record) for record in records]

    def replace(self, route_id: UUID, request: ReplaceTrafficRouteRequest) -> TrafficRoute:
        fingerprint = self._fingerprint(request)
        try:
            with self._database.transaction() as session:
                replay = session.execute(
                    select(TrafficRouteEventRecord).where(
                        TrafficRouteEventRecord.idempotency_key == request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if replay.route_id != route_id or replay.fingerprint != fingerprint:
                        raise DeliveryConflictError(
                            "Route retry token was already used for a different mutation"
                        )
                    return self._view(session, self._find(session, route_id))

                record = session.execute(
                    select(TrafficRouteRecord)
                    .where(TrafficRouteRecord.id == route_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if record is None:
                    raise DeliveryNotFoundError("Traffic route was not found")

                # A concurrent request can commit the same idempotency token while
                # this transaction waits for the route lock. Under READ COMMITTED,
                # checking again after the lock observes that completed mutation.
                replay = session.execute(
                    select(TrafficRouteEventRecord).where(
                        TrafficRouteEventRecord.idempotency_key == request.idempotency_key
                    )
                ).scalar_one_or_none()
                if replay is not None:
                    if replay.route_id != route_id or replay.fingerprint != fingerprint:
                        raise DeliveryConflictError(
                            "Route retry token was already used for a different mutation"
                        )
                    return self._view(session, record)

                if record.revision != request.expected_revision:
                    raise DeliveryConflictError(
                        f"Route revision conflict: expected {request.expected_revision}, "
                        f"current is {record.revision}"
                    )

                previous = self._allocation(session, record)
                current = self._validated_allocation(
                    session,
                    agent_name=record.agent_name,
                    environment=DeliveryEnvironment(record.environment),
                    stable_release_id=request.stable_release_id,
                    candidate_release_id=request.candidate_release_id,
                    candidate_weight_basis_points=request.candidate_weight_basis_points,
                )
                occurred_at = utc_now()
                previous_revision = record.revision
                record.stable_release_id = request.stable_release_id
                record.candidate_release_id = request.candidate_release_id
                record.candidate_weight_basis_points = request.candidate_weight_basis_points
                record.revision += 1
                record.updated_by = request.actor
                record.updated_at = occurred_at
                session.add(
                    TrafficRouteEventRecord(
                        id=uuid4(),
                        route_id=route_id,
                        event_type="route_replaced",
                        actor=request.actor,
                        reason=request.reason,
                        idempotency_key=request.idempotency_key,
                        fingerprint=fingerprint,
                        previous_revision=previous_revision,
                        new_revision=record.revision,
                        previous_allocation=previous.model_dump(mode="json"),
                        new_allocation=current.model_dump(mode="json"),
                        occurred_at=occurred_at,
                    )
                )
                session.flush()
                return self._view(session, record)
        except IntegrityError as exc:
            raise DeliveryConflictError("Route conflicts with persisted delivery state") from exc

    def events(self, route_id: UUID) -> list[TrafficRouteEvent]:
        with self._database.transaction() as session:
            self._find(session, route_id)
            records = session.execute(
                select(TrafficRouteEventRecord)
                .where(TrafficRouteEventRecord.route_id == route_id)
                .order_by(TrafficRouteEventRecord.occurred_at, TrafficRouteEventRecord.id)
            ).scalars()
            return [self._event(record) for record in records]

    @staticmethod
    def _fingerprint(request: CreateTrafficRouteRequest | ReplaceTrafficRouteRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _find(session: Session, route_id: UUID) -> TrafficRouteRecord:
        record = session.get(TrafficRouteRecord, route_id)
        if record is None:
            raise DeliveryNotFoundError("Traffic route was not found")
        return record

    @classmethod
    def _validated_allocation(
        cls,
        session: Session,
        *,
        agent_name: str,
        environment: DeliveryEnvironment,
        stable_release_id: UUID,
        candidate_release_id: UUID | None,
        candidate_weight_basis_points: int,
    ) -> TrafficAllocation:
        stable_record = cls._release(session, stable_release_id)
        cls._validate_release(
            stable_record,
            agent_name=agent_name,
            environment=environment,
            candidate=False,
        )
        candidate_record = None
        if candidate_release_id is not None:
            candidate_record = cls._release(session, candidate_release_id)
            cls._validate_release(
                candidate_record,
                agent_name=agent_name,
                environment=environment,
                candidate=True,
            )
        return TrafficAllocation(
            stable=cls._target(stable_record),
            candidate=cls._target(candidate_record) if candidate_record is not None else None,
            candidate_weight_basis_points=candidate_weight_basis_points,
        )

    @staticmethod
    def _release(session: Session, release_id: UUID) -> ReleaseRecord:
        record = session.get(ReleaseRecord, release_id)
        if record is None:
            raise DeliveryNotFoundError("Referenced release was not found")
        return record

    @staticmethod
    def _validate_release(
        record: ReleaseRecord,
        *,
        agent_name: str,
        environment: DeliveryEnvironment,
        candidate: bool,
    ) -> None:
        if record.agent_name != agent_name:
            raise DeliveryBlockedError("Route releases must belong to the routed agent")
        if not bool(record.gate.get("passed")):
            raise DeliveryBlockedError("Route releases must have passed all release gates")
        state = ReleaseState(record.state)
        if candidate:
            eligible = {ReleaseState.STAGED, ReleaseState.PRODUCTION}
        elif environment is DeliveryEnvironment.PRODUCTION:
            eligible = {ReleaseState.PRODUCTION}
        else:
            eligible = {ReleaseState.STAGED, ReleaseState.PRODUCTION}
        if state not in eligible:
            role = "Candidate" if candidate else "Stable"
            raise DeliveryBlockedError(
                f"{role} release state {state.value!r} is not eligible for "
                f"{environment.value} traffic"
            )

    @staticmethod
    def _target(record: ReleaseRecord) -> RouteTarget:
        return RouteTarget(
            release_id=record.id,
            agent_version_id=record.agent_version_id,
            agent_version=record.agent_version,
            provenance_hash=record.provenance_hash,
        )

    @classmethod
    def _allocation(cls, session: Session, record: TrafficRouteRecord) -> TrafficAllocation:
        stable = cls._release(session, record.stable_release_id)
        candidate = (
            cls._release(session, record.candidate_release_id)
            if record.candidate_release_id is not None
            else None
        )
        return TrafficAllocation(
            stable=cls._target(stable),
            candidate=cls._target(candidate) if candidate is not None else None,
            candidate_weight_basis_points=record.candidate_weight_basis_points,
        )

    @classmethod
    def _view(cls, session: Session, record: TrafficRouteRecord) -> TrafficRoute:
        return TrafficRoute(
            id=record.id,
            agent_name=record.agent_name,
            environment=DeliveryEnvironment(record.environment),
            allocation=cls._allocation(session, record),
            revision=record.revision,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _event(record: TrafficRouteEventRecord) -> TrafficRouteEvent:
        return TrafficRouteEvent(
            id=record.id,
            route_id=record.route_id,
            event_type=record.event_type,
            actor=record.actor,
            reason=record.reason,
            idempotency_key=record.idempotency_key,
            previous_revision=record.previous_revision,
            new_revision=record.new_revision,
            previous_allocation=(
                TrafficAllocation.model_validate(record.previous_allocation)
                if record.previous_allocation is not None
                else None
            ),
            new_allocation=TrafficAllocation.model_validate(record.new_allocation),
            occurred_at=record.occurred_at,
        )
