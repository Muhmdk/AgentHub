"""Integrity verification for persisted evaluation reports."""

from packages.contracts.evaluation import EvaluationRunReport
from packages.evaluation.catalog import artifact_hash


def report_artifact_hash(report: EvaluationRunReport) -> str:
    """Recompute the report hash without its self-referential hash field."""
    return artifact_hash(report.model_dump(mode="json", exclude={"artifact_hash"}))


def verify_report(report: EvaluationRunReport) -> None:
    """Reject a report whose serialized content no longer matches its hash."""
    if report_artifact_hash(report) != report.artifact_hash:
        raise ValueError("Evaluation report artifact hash does not match its content")
