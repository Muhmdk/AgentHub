"""Schema and compatibility tests for versioned agent manifests."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from packages.contracts.manifest import AgentManifest

ROOT = Path(__file__).parents[2]
MANIFESTS = sorted((ROOT / "data" / "manifests").glob("*.json"))


@pytest.mark.unit
@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: path.stem)
def test_v1_example_is_valid_in_json_schema_and_typed_contract(manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "agent-manifest-v1.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema).validate(payload)
    manifest = AgentManifest.model_validate(payload)

    assert manifest.schema_version == "agenthub.dev/v1"
    assert len(manifest.manifest_hash) == 64
    assert "@sha256:" in manifest.spec.runtime.image


@pytest.mark.unit
def test_manifest_hash_is_canonical_and_changes_with_executable_identity() -> None:
    payload = json.loads(MANIFESTS[0].read_text(encoding="utf-8"))
    first = AgentManifest.model_validate(payload)
    reordered = AgentManifest.model_validate(dict(reversed(payload.items())))
    changed = first.model_copy(
        update={
            "spec": first.spec.model_copy(
                update={"source": first.spec.source.model_copy(update={"commit_sha": "b" * 40})}
            )
        }
    )

    assert first.manifest_hash == reordered.manifest_hash
    assert first.manifest_hash != changed.manifest_hash


@pytest.mark.unit
def test_unknown_schema_version_is_rejected_instead_of_guessed() -> None:
    payload = json.loads(MANIFESTS[0].read_text(encoding="utf-8"))
    payload["schema_version"] = "agenthub.dev/v0"

    with pytest.raises(ValidationError):
        AgentManifest.model_validate(payload)


@pytest.mark.unit
def test_mutable_image_tag_and_short_source_sha_are_rejected() -> None:
    payload = json.loads(MANIFESTS[0].read_text(encoding="utf-8"))
    payload["spec"]["runtime"]["image"] = "ghcr.io/muhmdk/agenthub/inventory:latest"
    payload["spec"]["source"]["commit_sha"] = "main"

    with pytest.raises(ValidationError) as raised:
        AgentManifest.model_validate(payload)

    fields = {str(error["loc"][-1]) for error in raised.value.errors()}
    assert fields == {"commit_sha", "image"}


@pytest.mark.unit
def test_manifest_models_are_immutable() -> None:
    manifest = AgentManifest.model_validate_json(MANIFESTS[0].read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        manifest.metadata.__setattr__("version", "2.0.0")
