"""Print a deterministic top-k regression payload for a recovery drill."""

import argparse
import json
from datetime import UTC, datetime
from uuid import uuid4

from packages.contracts.delivery import DeliveryEnvironment
from packages.incidents.faults import TopKRegressionFault


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-top-k", type=int, default=5)
    parser.add_argument("--candidate-top-k", type=int, default=50)
    args = parser.parse_args()
    scenario = TopKRegressionFault(
        baseline_top_k=args.baseline_top_k,
        candidate_top_k=args.candidate_top_k,
    ).build(
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        release_id=uuid4(),
        route_id=uuid4(),
        canary_rollout_id=uuid4(),
        observed_at=datetime.now(UTC),
    )
    payload = {
        "baseline": scenario.baseline.__dict__,
        "candidate": scenario.candidate.__dict__,
        "signal": scenario.signal.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in scenario.evidence],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
