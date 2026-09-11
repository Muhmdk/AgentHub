"""Keep the tested policy bundle identical to the Helm-mounted copy."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "packaged"),
    [
        (
            ROOT / "policies" / "agenthub" / "authz.rego",
            ROOT / "deploy" / "helm" / "agenthub" / "files" / "policies" / "authz.rego",
        ),
        (
            ROOT / "policies" / "data.json",
            ROOT / "deploy" / "helm" / "agenthub" / "files" / "policies" / "data.json",
        ),
    ],
)
def test_helm_policy_bundle_matches_tested_source(source: Path, packaged: Path) -> None:
    assert packaged.read_bytes() == source.read_bytes()
