"""Candidate release lineage and promotion controls."""

from packages.release.lifecycle import can_transition, transition_reason

__all__ = ["can_transition", "transition_reason"]
