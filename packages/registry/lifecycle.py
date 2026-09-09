"""Explicit lifecycle state machine for immutable agent versions."""

from packages.contracts.registry import LifecycleState

ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.DRAFT: frozenset({LifecycleState.REGISTERED, LifecycleState.RETIRED}),
    LifecycleState.REGISTERED: frozenset({LifecycleState.EVALUATING, LifecycleState.RETIRED}),
    LifecycleState.EVALUATING: frozenset(
        {LifecycleState.APPROVED, LifecycleState.REJECTED, LifecycleState.RETIRED}
    ),
    LifecycleState.APPROVED: frozenset({LifecycleState.STAGED, LifecycleState.RETIRED}),
    LifecycleState.REJECTED: frozenset({LifecycleState.EVALUATING, LifecycleState.RETIRED}),
    LifecycleState.STAGED: frozenset(
        {LifecycleState.CANARY, LifecycleState.ROLLED_BACK, LifecycleState.RETIRED}
    ),
    LifecycleState.CANARY: frozenset(
        {LifecycleState.PRODUCTION, LifecycleState.ROLLED_BACK, LifecycleState.RETIRED}
    ),
    LifecycleState.PRODUCTION: frozenset({LifecycleState.ROLLED_BACK, LifecycleState.RETIRED}),
    LifecycleState.ROLLED_BACK: frozenset({LifecycleState.STAGED, LifecycleState.RETIRED}),
    LifecycleState.RETIRED: frozenset(),
}


def can_transition(previous: LifecycleState, target: LifecycleState) -> bool:
    return target in ALLOWED_TRANSITIONS[previous]


def transition_reason(previous: LifecycleState, target: LifecycleState) -> str:
    if can_transition(previous, target):
        return f"Transition from {previous.value} to {target.value} is permitted"
    return f"Transition from {previous.value} to {target.value} is not permitted"
