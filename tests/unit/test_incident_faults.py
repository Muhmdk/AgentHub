"""Canonical top-k fault-injection scenario coverage."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from packages.contracts.delivery import DeliveryEnvironment
from packages.contracts.incident import EvidenceKind
from packages.contracts.manifest import RetrievalSpec
from packages.contracts.retrieval import SearchRequest
from packages.incidents.faults import TopKRegressionFault


@pytest.mark.unit
def test_top_k_fault_is_measurable_and_holds_model_latency_constant() -> None:
    scenario = TopKRegressionFault().build(
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        release_id=uuid4(),
        route_id=uuid4(),
        canary_rollout_id=uuid4(),
        observed_at=datetime(2026, 9, 11, 9, tzinfo=UTC),
    )

    assert scenario.baseline.top_k == 5
    assert scenario.candidate.top_k == 50
    assert (
        scenario.candidate.retrieval_p95_latency_ms > scenario.baseline.retrieval_p95_latency_ms * 5
    )
    assert scenario.candidate.model_p95_latency_ms == scenario.baseline.model_p95_latency_ms
    assert scenario.signal.observed_value > scenario.signal.threshold
    assert [item.kind for item in scenario.evidence] == [
        EvidenceKind.CONFIG_DIFF,
        EvidenceKind.METRIC,
        EvidenceKind.METRIC,
    ]


@pytest.mark.unit
def test_runtime_and_manifest_contracts_accept_bounded_top_k_fifty() -> None:
    assert RetrievalSpec(corpus_id="retail", corpus_version="v1", top_k=50).top_k == 50
    assert (
        SearchRequest(query="snow", corpus_id="retail", corpus_version="v1", top_k=50).top_k == 50
    )

    with pytest.raises(ValueError, match="Fault requires"):
        TopKRegressionFault(baseline_top_k=50, candidate_top_k=5)
