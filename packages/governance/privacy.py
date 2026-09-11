"""Deterministic detection and redaction for supported PII classes."""

import re
from dataclasses import dataclass
from enum import StrEnum

from packages.contracts.runtime import ChatMessage, ModelRequest


class PIIKind(StrEnum):
    """PII formats with deterministic local detectors."""

    EMAIL = "email"
    PHONE = "phone"
    PAYMENT_CARD = "payment_card"
    CANADIAN_SIN = "canadian_sin"


@dataclass(frozen=True, order=True)
class PIIFinding:
    """One location-safe PII match; matched text is intentionally not retained."""

    start: int
    end: int
    kind: PIIKind


_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_CANADIAN_SIN = re.compile(r"(?<!\d)\d{3}[ -]\d{3}[ -]\d{3}(?!\d)")


def _luhn_valid(candidate: str) -> bool:
    digits = [int(character) for character in candidate if character.isdigit()]
    if not 9 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    parity = len(digits) % 2
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def detect_pii(value: str) -> list[PIIFinding]:
    """Return non-overlapping findings without retaining sensitive values."""
    candidates: list[PIIFinding] = []
    for match in _CANADIAN_SIN.finditer(value):
        if _luhn_valid(match.group()):
            candidates.append(PIIFinding(match.start(), match.end(), PIIKind.CANADIAN_SIN))
    for match in _PAYMENT_CARD.finditer(value):
        digits = sum(character.isdigit() for character in match.group())
        if digits >= 13 and _luhn_valid(match.group()):
            candidates.append(PIIFinding(match.start(), match.end(), PIIKind.PAYMENT_CARD))
    candidates.extend(
        PIIFinding(match.start(), match.end(), PIIKind.EMAIL) for match in _EMAIL.finditer(value)
    )
    candidates.extend(
        PIIFinding(match.start(), match.end(), PIIKind.PHONE) for match in _PHONE.finditer(value)
    )

    selected: list[PIIFinding] = []
    for finding in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
        if any(
            finding.start < existing.end and existing.start < finding.end for existing in selected
        ):
            continue
        selected.append(finding)
    return sorted(selected)


def redact_text(value: str) -> str:
    """Replace supported PII with stable type-preserving markers."""
    findings = detect_pii(value)
    if not findings:
        return value
    pieces: list[str] = []
    cursor = 0
    for finding in findings:
        pieces.append(value[cursor : finding.start])
        pieces.append(f"[REDACTED:{finding.kind.value.upper()}]")
        cursor = finding.end
    pieces.append(value[cursor:])
    return "".join(pieces)


def redact_model_request(request: ModelRequest) -> ModelRequest:
    """Return an equivalent immutable request with message content sanitized."""
    return request.model_copy(
        update={
            "messages": [
                ChatMessage(role=message.role, content=redact_text(message.content))
                for message in request.messages
            ]
        }
    )
