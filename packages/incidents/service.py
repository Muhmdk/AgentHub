"""Incident intake orchestration over deterministic detection and durable storage."""

from packages.contracts.incident import IncidentDetection, ObserveIncidentSignalRequest
from packages.incidents.detection import IncidentTriggerDetector
from packages.incidents.repository import IncidentStore


class IncidentService:
    """Create incidents only when a typed operational signal breaches policy."""

    def __init__(self, store: IncidentStore) -> None:
        self._store = store

    def observe(self, request: ObserveIncidentSignalRequest) -> IncidentDetection:
        evaluation = IncidentTriggerDetector.evaluate(request.signal)
        if not evaluation.breached:
            return IncidentDetection(detected=False, evaluation=evaluation)
        result = self._store.create(request.signal, evaluation, request.actor)
        return IncidentDetection(detected=True, evaluation=evaluation, result=result)
