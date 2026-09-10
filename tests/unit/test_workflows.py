"""Static policy checks for the GitHub Actions release boundary."""

import re
from pathlib import Path
from typing import cast

import pytest
import yaml

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_SHA = re.compile(r"^[^@]+@[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")


def _load(name: str) -> dict[str, object]:
    content = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


@pytest.mark.unit
def test_every_workflow_is_valid_yaml_with_read_only_default_permissions() -> None:
    paths = sorted(WORKFLOWS.glob("*.yml"))

    assert {path.name for path in paths} == {
        "candidate-evaluation.yml",
        "ci.yml",
        "infrastructure.yml",
        "release.yml",
    }
    for path in paths:
        document = _load(path.name)
        assert document["permissions"] == {"contents": "read"}
        assert isinstance(document["jobs"], dict)


@pytest.mark.unit
def test_external_actions_and_service_images_are_immutably_pinned() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        document = _load(path.name)
        jobs = cast(dict[str, dict[str, object]], document["jobs"])
        for job in jobs.values():
            if "uses" in job:
                assert str(job["uses"]).startswith("./")
            steps = cast(list[dict[str, str]], job.get("steps", []))
            for step in steps:
                if "uses" in step:
                    assert ACTION_SHA.fullmatch(step["uses"])
            services = cast(dict[str, dict[str, str]], job.get("services", {}))
            for service in services.values():
                assert IMAGE_DIGEST.fullmatch(service["image"])


@pytest.mark.unit
def test_pr_ci_covers_required_checks_and_preserves_quality_gate() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    for command in (
        "make lint",
        "make typecheck",
        "make test",
        "make security",
    ):
        assert command in workflow
    assert "name: Quality" in workflow
    assert "if: always()" in workflow


@pytest.mark.unit
def test_candidate_workflow_registers_evaluates_and_attaches_evidence() -> None:
    workflow = (WORKFLOWS / "candidate-evaluation.yml").read_text(encoding="utf-8")

    assert "packages.registry.bootstrap" in workflow
    assert "packages.evaluation" in workflow
    assert "packages.release candidate" in workflow
    assert "candidate-sbom.cdx.json" in workflow
    assert 'test "$GATE_PASSED" = true' in workflow


@pytest.mark.unit
def test_infrastructure_workflow_validates_committed_observability_assets() -> None:
    workflow = (WORKFLOWS / "infrastructure.yml").read_text(encoding="utf-8")

    assert list((ROOT / "infra/observability/grafana/dashboards").glob("*.json"))
    assert "infra/observability/grafana/dashboards/*.json" in workflow
    assert "--entrypoint promtool prometheus" in workflow
    assert "promtool check" not in workflow
    assert "promtool test" not in workflow


@pytest.mark.unit
def test_release_uses_least_privilege_oidc_and_digest_only_promotion() -> None:
    release_path = WORKFLOWS / "release.yml"
    workflow = _load("release.yml")
    text = release_path.read_text(encoding="utf-8")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    assert jobs["build"]["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    for environment in ("staging", "production"):
        assert jobs[environment]["environment"] == environment
        assert jobs[environment]["permissions"] == {
            "contents": "read",
            "id-token": "write",
        }
    assert "secrets." not in text
    assert "password: ${{ github.token }}" in text
    assert "HIGH,CRITICAL" in text
    assert 'exit-code: "1"' in text
    assert "@${{ steps.build.outputs.digest }}" in text
    assert "Verify no production rebuild" in text
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in text
