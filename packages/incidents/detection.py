"""Deterministic breach rules for operational incident signals."""

from packages.contracts.incident import IncidentSignal, IncidentTriggerType, TriggerEvaluation

_LOWER_BOUND_TRIGGERS = {
    IncidentTriggerType.QUALITY_REGRESSION,
    IncidentTriggerType.SAFETY_VIOLATION,
}
_INCLUSIVE_UPPER_BOUND_TRIGGERS = {IncidentTriggerType.SLO_BURN}


class IncidentTriggerDetector:
    """Evaluate sanitized measurements without model inference or side effects."""

    @staticmethod
    def evaluate(signal: IncidentSignal) -> TriggerEvaluation:
        if signal.trigger_type in _LOWER_BOUND_TRIGGERS:
            breached = signal.observed_value < signal.threshold
            operator = "<"
        elif signal.trigger_type in _INCLUSIVE_UPPER_BOUND_TRIGGERS:
            breached = signal.observed_value >= signal.threshold
            operator = ">="
        else:
            breached = signal.observed_value > signal.threshold
            operator = ">"
        disposition = "breached" if breached else "did not breach"
        return TriggerEvaluation(
            breached=breached,
            operator=operator,
            observed_value=signal.observed_value,
            threshold=signal.threshold,
            reason=(
                f"{signal.signal_name} {disposition} the {operator} "
                f"{signal.threshold:g} incident threshold"
            ),
        )
