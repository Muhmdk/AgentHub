"""Attribute allowlisting, bounded dimensions, and defensive value redaction."""

import re
from collections.abc import Mapping

from opentelemetry.util.types import AttributeValue

from packages.observability.conventions import (
    METRIC_ATTRIBUTE_ALLOWLIST,
    SPAN_ATTRIBUTE_ALLOWLIST,
    Attribute,
)

type TelemetryAttributes = dict[str, AttributeValue]
type AttributeMapping = Mapping[Attribute, AttributeValue] | Mapping[str, AttributeValue]

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b")
_SECRET = re.compile(r"(?i)(?:bearer\s+[a-z0-9._-]+|(?:sk|api|token|secret)[_-]?[a-z0-9]{12,})")
_DIMENSION = re.compile(r"^[/A-Za-z0-9][A-Za-z0-9._:/{}-]{0,79}$")


def redact_value(value: AttributeValue) -> AttributeValue:
    """Redact common secret/PII forms and cap exported string size."""
    if not isinstance(value, str):
        return value
    cleaned = _SECRET.sub("[REDACTED]", value)
    cleaned = _EMAIL.sub("[REDACTED]", cleaned)
    cleaned = _PHONE.sub("[REDACTED]", cleaned)
    return cleaned[:128]


def bounded_dimension(value: str | None) -> str:
    """Return a bounded label value or one stable fallback bucket."""
    if value and _DIMENSION.fullmatch(value):
        return value
    return "unknown"


def span_attributes(values: AttributeMapping) -> TelemetryAttributes:
    """Allow only declared keys and redact every retained value."""
    return {
        str(key): redact_value(value)
        for key, value in values.items()
        if key in SPAN_ATTRIBUTE_ALLOWLIST or str(key) in SPAN_ATTRIBUTE_ALLOWLIST
    }


def metric_attributes(values: AttributeMapping) -> TelemetryAttributes:
    """Allow only bounded metric dimensions and collapse unsafe strings."""
    retained: TelemetryAttributes = {}
    for key, value in values.items():
        normalized_key = str(key)
        if (
            key not in METRIC_ATTRIBUTE_ALLOWLIST
            and normalized_key not in METRIC_ATTRIBUTE_ALLOWLIST
        ):
            continue
        retained[normalized_key] = bounded_dimension(value) if isinstance(value, str) else value
    return retained
