"""Deterministic safeguards for instructions embedded in retrieved data."""

_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "call the tool",
    "override policy",
)


def contains_embedded_instruction(content: str) -> bool:
    """Identify supported prompt-injection phrases in untrusted retrieved text."""
    normalized = content.casefold()
    return any(marker in normalized for marker in _INJECTION_MARKERS)
