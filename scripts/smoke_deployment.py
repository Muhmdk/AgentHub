"""Run bounded AgentHub smoke checks against a local or deployed HTTP endpoint."""

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from packages.contracts.runtime import JsonValue


class SmokeFailure(RuntimeError):
    """Safe deployment verification failure."""


class JsonTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonValue: ...


class UrllibTransport:
    """Small HTTP transport that never prints response bodies or authorization values."""

    def __init__(self, base_url: str, timeout_seconds: float, bearer_token: str | None) -> None:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Smoke base URL must be an HTTP or HTTPS origin")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Non-local smoke endpoints must use HTTPS")
        self._base_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        self._timeout_seconds = timeout_seconds
        self._bearer_token = bearer_token

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonValue:
        request_headers = {"Accept": "application/json", **(headers or {})}
        if self._bearer_token:
            request_headers["Authorization"] = f"Bearer {self._bearer_token}"
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                decoded = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"{method} {path} failed") from exc
        return cast(JsonValue, decoded)


@dataclass(frozen=True)
class SmokeReport:
    service_version: str
    environment: str
    inventory_model: str
    knowledge_model: str
    registry_created: bool
    evaluation_run_id: str
    evaluation_gate_passed: bool


def _object(value: JsonValue, operation: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise SmokeFailure(f"{operation} returned an invalid contract")
    return value


def _nonempty_list(value: JsonValue | None, operation: str) -> list[JsonValue]:
    if not isinstance(value, list) or not value:
        raise SmokeFailure(f"{operation} returned no evidence")
    return value


def run_smoke(
    transport: JsonTransport,
    manifest: Mapping[str, JsonValue],
    *,
    expected_model_prefix: str | None = None,
    environment: str = "smoke",
    caller_identity: str = "local/deployment-smoke",
) -> SmokeReport:
    """Verify health, registry, evaluation, and model/search agent paths."""
    live = _object(transport.request("GET", "/health/live"), "liveness")
    ready = _object(transport.request("GET", "/health/ready"), "readiness")
    if live.get("status") != "ok" or ready.get("status") != "ready":
        raise SmokeFailure("AgentHub health checks did not pass")

    version = _object(transport.request("GET", "/version"), "version")
    service_version = version.get("version")
    deployed_environment = version.get("environment")
    if not isinstance(service_version, str) or not isinstance(deployed_environment, str):
        raise SmokeFailure("Version endpoint returned an invalid contract")

    registration = _object(
        transport.request(
            "POST",
            "/registry/agents",
            payload=manifest,
            headers={"X-AgentHub-Actor": "post-deploy-smoke"},
        ),
        "registration",
    )
    registry_created = registration.get("created")
    if not isinstance(registry_created, bool):
        raise SmokeFailure("Registration endpoint returned an invalid contract")
    registered = _object(
        transport.request("GET", "/registry/agents/inventory-agent"), "registry lookup"
    )
    if registered.get("name") != "inventory-agent":
        raise SmokeFailure("Registered inventory agent was not readable")

    inventory = _object(
        transport.request(
            "POST",
            "/gateway/agents/inventory-agent/invoke",
            payload={
                "query": "Which Toronto stores may run low on snow shovels this weekend?",
                "seed": 11,
                "as_of": "2026-09-08",
            },
            headers={"X-AgentHub-Identity": caller_identity},
        ),
        "inventory invocation",
    )
    inventory_model = inventory.get("model")
    if not isinstance(inventory.get("answer"), str) or not isinstance(inventory_model, str):
        raise SmokeFailure("Inventory invocation returned an invalid contract")
    _nonempty_list(inventory.get("citations"), "inventory invocation")
    _nonempty_list(inventory.get("tool_calls"), "inventory invocation")

    knowledge = _object(
        transport.request(
            "POST",
            "/gateway/agents/knowledge-agent/invoke",
            payload={"query": "Can I return an unopened product after 20 days?", "seed": 4},
            headers={"X-AgentHub-Identity": caller_identity},
        ),
        "knowledge invocation",
    )
    knowledge_model = knowledge.get("model")
    if not isinstance(knowledge.get("answer"), str) or not isinstance(knowledge_model, str):
        raise SmokeFailure("Knowledge invocation returned an invalid contract")
    citations = _nonempty_list(knowledge.get("citations"), "knowledge invocation")
    retrieval = _object(knowledge.get("retrieval"), "knowledge retrieval")
    result_ids = _nonempty_list(retrieval.get("result_ids"), "knowledge retrieval")
    first_citation = _object(citations[0], "knowledge citation")
    if first_citation.get("source_id") not in result_ids:
        raise SmokeFailure("Knowledge citation was not grounded in retrieval results")

    if expected_model_prefix and (
        not inventory_model.startswith(expected_model_prefix)
        or not knowledge_model.startswith(expected_model_prefix)
    ):
        raise SmokeFailure("Agent invocation used an unexpected model provider")

    evaluation = _object(
        transport.request(
            "POST",
            "/evaluations/runs",
            payload={
                "agent_name": "inventory-agent",
                "agent_version": "1.0.0",
                "suite_id": "inventory-agent-suite",
                "environment": environment,
            },
        ),
        "evaluation run",
    )
    run_id = evaluation.get("run_id")
    gate = _object(evaluation.get("gate"), "evaluation gate")
    gate_passed = gate.get("passed")
    case_results = _nonempty_list(evaluation.get("case_results"), "evaluation run")
    if not isinstance(run_id, str) or not isinstance(gate_passed, bool):
        raise SmokeFailure("Evaluation endpoint returned an invalid contract")
    for case in case_results:
        case_result = _object(case, "evaluation case")
        if case_result.get("status") != "completed":
            raise SmokeFailure("Evaluation run contained an incomplete case")
    if not gate_passed:
        raise SmokeFailure("Evaluation gate did not pass")

    return SmokeReport(
        service_version=service_version,
        environment=deployed_environment,
        inventory_model=inventory_model,
        knowledge_model=knowledge_model,
        registry_created=registry_created,
        evaluation_run_id=run_id,
        evaluation_gate_passed=gate_passed,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/manifests/inventory-agent-v1.json")
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--expected-model-prefix")
    parser.add_argument("--environment", default="smoke")
    parsed = parser.parse_args(arguments)
    if parsed.timeout_seconds <= 0 or parsed.timeout_seconds > 120:
        parser.error("--timeout-seconds must be greater than zero and no more than 120")
    try:
        manifest_raw = json.loads(parsed.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest_raw, dict):
            raise ValueError("Manifest must contain a JSON object")
        bearer_token = os.getenv("AGENTHUB_SMOKE_BEARER_TOKEN")
        transport = UrllibTransport(
            parsed.base_url,
            parsed.timeout_seconds,
            bearer_token,
        )
        report = run_smoke(
            transport,
            cast(dict[str, JsonValue], manifest_raw),
            expected_model_prefix=parsed.expected_model_prefix,
            environment=parsed.environment,
            caller_identity=os.getenv(
                "AGENTHUB_SMOKE_IDENTITY",
                "service/deployment-smoke" if bearer_token else "local/deployment-smoke",
            ),
        )
    except (OSError, ValueError, SmokeFailure) as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
