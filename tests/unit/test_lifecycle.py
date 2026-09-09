"""Exhaustive table tests for the agent-version lifecycle state machine."""

import pytest

from packages.contracts.registry import LifecycleState
from packages.registry.lifecycle import (
    ALLOWED_TRANSITIONS,
    can_transition,
    transition_reason,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("previous", "target"),
    [(previous, target) for previous in LifecycleState for target in LifecycleState],
)
def test_every_lifecycle_state_pair_matches_declared_transition_table(
    previous: LifecycleState, target: LifecycleState
) -> None:
    expected = target in ALLOWED_TRANSITIONS[previous]

    assert can_transition(previous, target) is expected
    assert ("is permitted" in transition_reason(previous, target)) is expected


@pytest.mark.unit
def test_retired_is_terminal_and_self_transitions_are_forbidden() -> None:
    assert ALLOWED_TRANSITIONS[LifecycleState.RETIRED] == frozenset()
    assert all(not can_transition(state, state) for state in LifecycleState)
