"""State coverage for non-skippable canary progression."""

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import CanaryAction, CanaryProgress, CanaryState
from packages.delivery.canary import CanaryStateMachine, InvalidCanaryTransition


def test_canary_advances_through_every_weight_before_completion() -> None:
    progress = CanaryProgress()
    observed = [(progress.state, CanaryStateMachine.weight_basis_points(progress))]

    progress = CanaryStateMachine.transition(progress, CanaryAction.START)
    observed.append((progress.state, CanaryStateMachine.weight_basis_points(progress)))
    for _ in range(4):
        progress = CanaryStateMachine.transition(progress, CanaryAction.PROMOTE)
        observed.append((progress.state, CanaryStateMachine.weight_basis_points(progress)))

    assert observed == [
        (CanaryState.PENDING, 0),
        (CanaryState.FIVE_PERCENT, 500),
        (CanaryState.TWENTY_FIVE_PERCENT, 2_500),
        (CanaryState.FIFTY_PERCENT, 5_000),
        (CanaryState.ONE_HUNDRED_PERCENT, 10_000),
        (CanaryState.COMPLETED, 10_000),
    ]


@pytest.mark.parametrize(
    "state",
    [
        CanaryState.PENDING,
        CanaryState.FIVE_PERCENT,
        CanaryState.TWENTY_FIVE_PERCENT,
        CanaryState.FIFTY_PERCENT,
        CanaryState.ONE_HUNDRED_PERCENT,
    ],
)
def test_pause_and_resume_return_to_exact_active_stage(state: CanaryState) -> None:
    progress = CanaryProgress(state=state)

    paused = CanaryStateMachine.transition(progress, CanaryAction.PAUSE)
    resumed = CanaryStateMachine.transition(paused, CanaryAction.RESUME)

    assert paused == CanaryProgress(state=CanaryState.PAUSED, resume_state=state)
    assert CanaryStateMachine.weight_basis_points(paused) == CanaryStateMachine.weight_basis_points(
        progress
    )
    assert resumed == progress


@pytest.mark.parametrize(
    "progress",
    [
        CanaryProgress(),
        CanaryProgress(state=CanaryState.FIVE_PERCENT),
        CanaryProgress(
            state=CanaryState.PAUSED,
            resume_state=CanaryState.TWENTY_FIVE_PERCENT,
        ),
    ],
)
def test_abort_rolls_back_to_zero_traffic(progress: CanaryProgress) -> None:
    rolled_back = CanaryStateMachine.transition(progress, CanaryAction.ABORT)

    assert rolled_back.state is CanaryState.ROLLED_BACK
    assert CanaryStateMachine.weight_basis_points(rolled_back) == 0


@pytest.mark.parametrize(
    ("progress", "action"),
    [
        (CanaryProgress(), CanaryAction.PROMOTE),
        (CanaryProgress(state=CanaryState.FIVE_PERCENT), CanaryAction.START),
        (CanaryProgress(state=CanaryState.COMPLETED), CanaryAction.ABORT),
        (CanaryProgress(state=CanaryState.ROLLED_BACK), CanaryAction.START),
        (CanaryProgress(state=CanaryState.FIVE_PERCENT), CanaryAction.RESUME),
    ],
)
def test_invalid_or_skipped_transitions_are_rejected(
    progress: CanaryProgress, action: CanaryAction
) -> None:
    with pytest.raises(InvalidCanaryTransition):
        CanaryStateMachine.transition(progress, action)


def test_progress_contract_rejects_missing_or_stale_resume_state() -> None:
    with pytest.raises(ValidationError, match="last active"):
        CanaryProgress(state=CanaryState.PAUSED)
    with pytest.raises(ValidationError, match="Only paused"):
        CanaryProgress(
            state=CanaryState.FIVE_PERCENT,
            resume_state=CanaryState.PENDING,
        )
