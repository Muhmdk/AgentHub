"""Sanitized adapters for telemetry, releases, and executable configuration."""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from opentelemetry.util.types import AttributeValue

from packages.contracts.incident import EvidenceInput, EvidenceKind
from packages.contracts.registry import AgentVersionView
from packages.contracts.release import ReleaseEventView, ReleaseView
from packages.contracts.runtime import JsonValue
from packages.observability.privacy import metric_attributes, redact_value
from packages.observability.telemetry import Observation


class TelemetryEvidenceAdapter:
    """Convert bounded in-process observations into sanitized metric evidence."""

    @staticmethod
    def collect(
        observations: list[Observation],
        *,
        idempotency_prefix: str,
        source_ref: str,
    ) -> list[EvidenceInput]:
        items: list[EvidenceInput] = []
        for observation in sorted(observations, key=lambda event: event.occurred_at):
            occurred_at = datetime.fromtimestamp(observation.occurred_at, UTC)
            attributes = metric_attributes(observation.attributes)
            identity = _hash(
                {
                    "occurred_at": observation.occurred_at,
                    "signal": observation.signal,
                    "value": observation.value,
                    "attributes": _json_mapping(attributes),
                }
            )
            items.append(
                EvidenceInput(
                    idempotency_key=_bounded_key(idempotency_prefix, identity[:16]),
                    kind=EvidenceKind.METRIC,
                    source_ref=f"{source_ref}#{identity}",
                    summary=f"Observed bounded metric {observation.signal}",
                    occurred_at=occurred_at,
                    subject_id=observation.signal,
                    attributes={
                        "signal": observation.signal,
                        "value": observation.value,
                        "dimensions": _json_mapping(attributes),
                    },
                )
            )
        return items


class ReleaseEvidenceAdapter:
    """Convert immutable release lineage and transitions into deployment evidence."""

    @staticmethod
    def collect(release: ReleaseView, events: list[ReleaseEventView]) -> list[EvidenceInput]:
        return [
            EvidenceInput(
                idempotency_key=_bounded_key("release-evidence", str(event.id)),
                kind=EvidenceKind.DEPLOYMENT,
                source_ref=f"release://{release.id}/events/{event.id}",
                summary=f"Release transitioned to {event.new_state.value}",
                occurred_at=event.occurred_at,
                subject_id=str(release.id),
                attributes={
                    "agent_name": release.agent_name,
                    "agent_version": release.agent_version,
                    "event_type": event.event_type,
                    "previous_state": (
                        event.previous_state.value if event.previous_state is not None else None
                    ),
                    "new_state": event.new_state.value,
                    "provenance_hash": event.provenance_hash,
                },
            )
            for event in events
        ]


class ConfigEvidenceAdapter:
    """Create a redacted field-level diff between immutable agent manifests."""

    @staticmethod
    def compare(previous: AgentVersionView, current: AgentVersionView) -> EvidenceInput:
        before = _flatten(previous.manifest.model_dump(mode="json"))
        after = _flatten(current.manifest.model_dump(mode="json"))
        changes: dict[str, JsonValue] = {}
        for path in sorted(before.keys() | after.keys()):
            if before.get(path) != after.get(path):
                changes[path] = {
                    "before": _sanitize(before.get(path)),
                    "after": _sanitize(after.get(path)),
                }
        return EvidenceInput(
            idempotency_key=_bounded_key(
                "config-diff", f"{previous.manifest_hash}-{current.manifest_hash}"
            ),
            kind=EvidenceKind.CONFIG_DIFF,
            source_ref=f"registry://versions/{previous.id}/compare/{current.id}",
            summary=(
                f"Agent manifest changed from {previous.version} to {current.version} "
                f"across {len(changes)} fields"
            ),
            occurred_at=current.created_at,
            subject_id=str(current.id),
            attributes={
                "previous_version": previous.version,
                "current_version": current.version,
                "previous_manifest_hash": previous.manifest_hash,
                "current_manifest_hash": current.manifest_hash,
                "changes": changes,
            },
        )


def _flatten(value: JsonValue, path: str = "") -> dict[str, JsonValue]:
    if isinstance(value, dict):
        flattened: dict[str, JsonValue] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            flattened.update(_flatten(child, child_path))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, child in enumerate(value):
            flattened.update(_flatten(child, f"{path}[{index}]"))
        return flattened or {path: []}
    return {path: value}


def _sanitize(value: JsonValue | None) -> JsonValue:
    if isinstance(value, str):
        return cast(str, redact_value(value))
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key[:100]: _sanitize(item) for key, item in list(value.items())[:100]}
    return value


def _json_mapping(values: Mapping[str, AttributeValue]) -> dict[str, JsonValue]:
    return {key: _attribute_value(value) for key, value in values.items()}


def _attribute_value(value: AttributeValue) -> JsonValue:
    if isinstance(value, tuple):
        return [_attribute_value(item) for item in value]
    return cast(JsonValue, value)


def _bounded_key(prefix: str, suffix: str) -> str:
    candidate = f"{prefix}-{suffix}"
    if len(candidate) <= 128:
        return candidate
    return f"{prefix[:63]}-{hashlib.sha256(candidate.encode()).hexdigest()}"


def _hash(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
