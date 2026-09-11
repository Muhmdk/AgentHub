"""Content-addressed, append-only incident evidence persistence."""

import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.contracts.incident import EvidenceCollectionResult, EvidenceInput, IncidentEvidence
from packages.incidents.models import IncidentEvidenceRecord, IncidentRecord
from packages.incidents.repository import IncidentNotFoundError
from packages.registry.database import Database
from packages.registry.models import utc_now


class EvidenceConflictError(RuntimeError):
    """An evidence retry token conflicts with an immutable stored item."""


class IncidentEvidenceStore(Protocol):
    def append(
        self, incident_id: UUID, item: EvidenceInput, actor: str
    ) -> EvidenceCollectionResult: ...

    def list_evidence(self, incident_id: UUID) -> list[IncidentEvidence]: ...


class IncidentEvidenceRepository:
    """Persist each evidence item atomically and replay concurrent retries safely."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def append(
        self, incident_id: UUID, item: EvidenceInput, actor: str
    ) -> EvidenceCollectionResult:
        fingerprint = self._fingerprint(incident_id, item, actor)
        content_hash = self._content_hash(item)
        try:
            return self._insert(incident_id, item, actor, fingerprint, content_hash)
        except IntegrityError:
            return self._replay(incident_id, item, fingerprint)

    def collect(
        self, incident_id: UUID, items: list[EvidenceInput], actor: str
    ) -> list[EvidenceCollectionResult]:
        return [self.append(incident_id, item, actor) for item in items]

    def list_evidence(self, incident_id: UUID) -> list[IncidentEvidence]:
        with self._database.transaction() as session:
            self._require_incident(session, incident_id)
            records = session.execute(
                select(IncidentEvidenceRecord)
                .where(IncidentEvidenceRecord.incident_id == incident_id)
                .order_by(IncidentEvidenceRecord.occurred_at, IncidentEvidenceRecord.id)
            ).scalars()
            return [self._view(record) for record in records]

    def _insert(
        self,
        incident_id: UUID,
        item: EvidenceInput,
        actor: str,
        fingerprint: str,
        content_hash: str,
    ) -> EvidenceCollectionResult:
        with self._database.transaction() as session:
            self._require_incident(session, incident_id)
            replay = session.execute(
                select(IncidentEvidenceRecord).where(
                    IncidentEvidenceRecord.idempotency_key == item.idempotency_key
                )
            ).scalar_one_or_none()
            if replay is not None:
                return self._validate_replay(replay, incident_id, fingerprint)
            record = IncidentEvidenceRecord(
                id=uuid4(),
                incident_id=incident_id,
                kind=item.kind.value,
                source_ref=item.source_ref,
                summary=item.summary,
                occurred_at=item.occurred_at,
                subject_id=item.subject_id,
                attributes=item.attributes,
                content_hash=content_hash,
                idempotency_key=item.idempotency_key,
                fingerprint=fingerprint,
                collected_by=actor,
                collected_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return EvidenceCollectionResult(created=True, evidence=self._view(record))

    def _replay(
        self, incident_id: UUID, item: EvidenceInput, fingerprint: str
    ) -> EvidenceCollectionResult:
        with self._database.transaction() as session:
            record = session.execute(
                select(IncidentEvidenceRecord).where(
                    IncidentEvidenceRecord.idempotency_key == item.idempotency_key
                )
            ).scalar_one_or_none()
            if record is None:
                raise EvidenceConflictError("Evidence conflicts with persisted incident state")
            return self._validate_replay(record, incident_id, fingerprint)

    @staticmethod
    def _validate_replay(
        record: IncidentEvidenceRecord, incident_id: UUID, fingerprint: str
    ) -> EvidenceCollectionResult:
        if record.incident_id != incident_id or record.fingerprint != fingerprint:
            raise EvidenceConflictError(
                "Evidence retry token was already used for a different immutable item"
            )
        return EvidenceCollectionResult(
            created=False, evidence=IncidentEvidenceRepository._view(record)
        )

    @staticmethod
    def _require_incident(session: Session, incident_id: UUID) -> None:
        if session.get(IncidentRecord, incident_id) is None:
            raise IncidentNotFoundError("Incident was not found")

    @staticmethod
    def _content_hash(item: EvidenceInput) -> str:
        content = item.model_dump(mode="json", exclude={"idempotency_key"})
        canonical = json.dumps(content, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _fingerprint(incident_id: UUID, item: EvidenceInput, actor: str) -> str:
        canonical = json.dumps(
            {
                "actor": actor,
                "incident_id": str(incident_id),
                "item": item.model_dump(mode="json"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _view(record: IncidentEvidenceRecord) -> IncidentEvidence:
        return IncidentEvidence(
            id=record.id,
            incident_id=record.incident_id,
            kind=record.kind,
            source_ref=record.source_ref,
            summary=record.summary,
            occurred_at=record.occurred_at,
            subject_id=record.subject_id,
            attributes=record.attributes,
            content_hash=record.content_hash,
            idempotency_key=record.idempotency_key,
            collected_by=record.collected_by,
            collected_at=record.collected_at,
        )
