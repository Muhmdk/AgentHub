"""Validate security invariants that Kubernetes schemas cannot express."""

import argparse
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


def _mapping(value: object, path: str, failures: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        failures.append(f"{path} must be an object")
        return {}
    return value


def _pod_specs(documents: Iterable[Mapping[str, Any]]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for document in documents:
        kind = document.get("kind")
        metadata = document.get("metadata", {})
        name = metadata.get("name", "unnamed") if isinstance(metadata, dict) else "unnamed"
        if kind == "Deployment":
            yield f"Deployment/{name}", document["spec"]["template"]["spec"]
        elif kind == "Job":
            yield f"Job/{name}", document["spec"]["template"]["spec"]


def validate(documents: Sequence[Mapping[str, Any]], require_image_digest: bool) -> list[str]:
    """Return all security-contract violations in a rendered manifest stream."""
    failures: list[str] = []
    kinds = {str(document.get("kind")) for document in documents}
    for required_kind in {
        "ConfigMap",
        "Deployment",
        "HorizontalPodAutoscaler",
        "Job",
        "NetworkPolicy",
        "SecretProviderClass",
        "Service",
        "ServiceAccount",
    }:
        if required_kind not in kinds:
            failures.append(f"dev render is missing {required_kind}")

    for resource_name, pod_spec in _pod_specs(documents):
        pod_security = _mapping(
            pod_spec.get("securityContext"), f"{resource_name} pod security", failures
        )
        if pod_security.get("runAsNonRoot") is not True:
            failures.append(f"{resource_name} must run as non-root")
        if (
            _mapping(pod_security.get("seccompProfile"), f"{resource_name} seccomp", failures).get(
                "type"
            )
            != "RuntimeDefault"
        ):
            failures.append(f"{resource_name} must use RuntimeDefault seccomp")
        if pod_spec.get("automountServiceAccountToken") is not False:
            failures.append(f"{resource_name} must disable default service-account token mounts")
        pod_metadata = next(
            document["spec"]["template"].get("metadata", {})
            for document in documents
            if resource_name == f"{document.get('kind')}/{document.get('metadata', {}).get('name')}"
        )
        if pod_metadata.get("labels", {}).get("azure.workload.identity/use") != "true":
            failures.append(f"{resource_name} must opt in to Azure workload identity")

        containers = pod_spec.get("containers")
        if not isinstance(containers, list) or not containers:
            failures.append(f"{resource_name} must define at least one container")
            continue
        for container in containers:
            if not isinstance(container, dict):
                failures.append(f"{resource_name} has an invalid container")
                continue
            container_name = f"{resource_name}/{container.get('name', 'unnamed')}"
            image = container.get("image")
            if require_image_digest and (not isinstance(image, str) or "@sha256:" not in image):
                failures.append(f"{container_name} must use a sha256 image digest")
            security = _mapping(
                container.get("securityContext"), f"{container_name} security", failures
            )
            if security.get("allowPrivilegeEscalation") is not False:
                failures.append(f"{container_name} must disable privilege escalation")
            if security.get("readOnlyRootFilesystem") is not True:
                failures.append(f"{container_name} must use a read-only root filesystem")
            capabilities = _mapping(
                security.get("capabilities"), f"{container_name} capabilities", failures
            )
            if "ALL" not in capabilities.get("drop", []):
                failures.append(f"{container_name} must drop all Linux capabilities")
            resources = _mapping(
                container.get("resources"), f"{container_name} resources", failures
            )
            if not resources.get("requests") or not resources.get("limits"):
                failures.append(f"{container_name} must define requests and limits")

    deployments = [document for document in documents if document.get("kind") == "Deployment"]
    for deployment in deployments:
        containers = deployment["spec"]["template"]["spec"]["containers"]
        for container in containers:
            for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
                if probe not in container:
                    failures.append(f"Deployment container must define {probe}")

    for document in documents:
        kind = document.get("kind")
        if kind == "ServiceAccount":
            if document.get("automountServiceAccountToken") is not False:
                failures.append("ServiceAccount must disable default token mounts")
            annotations = document.get("metadata", {}).get("annotations", {})
            if not annotations.get("azure.workload.identity/client-id"):
                failures.append("ServiceAccount must declare its Azure workload identity client ID")
        if kind == "HorizontalPodAutoscaler":
            spec = document.get("spec", {})
            if spec.get("minReplicas") != 1 or not 1 < spec.get("maxReplicas", 0) <= 2:
                failures.append("HPA must remain bounded between one and two replicas")
        if kind == "NetworkPolicy":
            policy_types = set(document.get("spec", {}).get("policyTypes", []))
            if policy_types != {"Ingress", "Egress"}:
                failures.append("NetworkPolicy must govern both ingress and egress")
        if kind == "SecretProviderClass":
            spec = document.get("spec", {})
            if spec.get("provider") != "azure" or not spec.get("parameters", {}).get("clientID"):
                failures.append("SecretProviderClass must use the explicit Azure workload identity")

    return failures


def load_documents(path: Path) -> list[Mapping[str, Any]]:
    """Load one rendered multi-document YAML file."""
    documents: list[Mapping[str, Any]] = []
    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if document is None:
            continue
        if not isinstance(document, dict):
            raise ValueError("Rendered Kubernetes documents must be objects")
        documents.append(document)
    return documents


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--require-image-digest", action="store_true")
    parsed = parser.parse_args(arguments)
    failures = validate(load_documents(parsed.manifest), parsed.require_image_digest)
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    print("Kubernetes security contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
