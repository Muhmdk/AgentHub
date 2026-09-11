"""Strict progressive-delivery canary state machine."""

from packages.contracts.delivery import CanaryAction, CanaryProgress, CanaryState


class InvalidCanaryTransition(ValueError):
    """Requested canary action is not valid from the current state."""


_PROMOTIONS = {
    CanaryState.FIVE_PERCENT: CanaryState.TWENTY_FIVE_PERCENT,
    CanaryState.TWENTY_FIVE_PERCENT: CanaryState.FIFTY_PERCENT,
    CanaryState.FIFTY_PERCENT: CanaryState.ONE_HUNDRED_PERCENT,
    CanaryState.ONE_HUNDRED_PERCENT: CanaryState.COMPLETED,
}
_ACTIVE_STATES = {
    CanaryState.PENDING,
    CanaryState.FIVE_PERCENT,
    CanaryState.TWENTY_FIVE_PERCENT,
    CanaryState.FIFTY_PERCENT,
    CanaryState.ONE_HUNDRED_PERCENT,
}
_WEIGHTS = {
    CanaryState.PENDING: 0,
    CanaryState.FIVE_PERCENT: 500,
    CanaryState.TWENTY_FIVE_PERCENT: 2_500,
    CanaryState.FIFTY_PERCENT: 5_000,
    CanaryState.ONE_HUNDRED_PERCENT: 10_000,
    CanaryState.COMPLETED: 10_000,
    CanaryState.ROLLED_BACK: 0,
}


class CanaryStateMachine:
    """Apply one non-skippable action and derive its traffic weight."""

    @staticmethod
    def transition(progress: CanaryProgress, action: CanaryAction) -> CanaryProgress:
        state = progress.state
        if action is CanaryAction.ABORT and state not in {
            CanaryState.COMPLETED,
            CanaryState.ROLLED_BACK,
        }:
            return CanaryProgress(state=CanaryState.ROLLED_BACK)
        if action is CanaryAction.PAUSE and state in _ACTIVE_STATES:
            return CanaryProgress(state=CanaryState.PAUSED, resume_state=state)
        if action is CanaryAction.RESUME and state is CanaryState.PAUSED:
            assert progress.resume_state is not None
            return CanaryProgress(state=progress.resume_state)
        if action is CanaryAction.START and state is CanaryState.PENDING:
            return CanaryProgress(state=CanaryState.FIVE_PERCENT)
        if action is CanaryAction.PROMOTE and state in _PROMOTIONS:
            return CanaryProgress(state=_PROMOTIONS[state])
        raise InvalidCanaryTransition(f"Cannot {action.value} a canary from {state.value}")

    @staticmethod
    def weight_basis_points(progress: CanaryProgress) -> int:
        """Map active, paused, and terminal progress to its intended route weight."""
        state = progress.resume_state if progress.state is CanaryState.PAUSED else progress.state
        assert state is not None
        return _WEIGHTS[state]
