"""Load and hash immutable evaluation inputs from the repository catalog."""

import hashlib
import json
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel

from packages.contracts.evaluation import EvaluationDataset, EvaluationSuite, GateProfile

ModelT = TypeVar("ModelT", bound=BaseModel)


def canonical_json(value: object) -> bytes:
    """Serialize a JSON-compatible value using the artifact hashing convention."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def artifact_hash(value: object) -> str:
    """Return a reproducible SHA-256 hash for a JSON-compatible artifact."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


class EvaluationCatalog:
    """Read versioned evaluation definitions from a fixed directory tree."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "data" / "evals"

    def dataset(self, dataset_id: str, version: str = "1.0.0") -> EvaluationDataset:
        return self._load("datasets", dataset_id, version, EvaluationDataset)

    def suite(self, suite_id: str, version: str = "1.0.0") -> EvaluationSuite:
        return self._load("suites", suite_id, version, EvaluationSuite)

    def gate_profile(self, profile_id: str, version: str = "1.0.0") -> GateProfile:
        return self._load("gates", profile_id, version, GateProfile)

    def resolve(
        self, suite_id: str, version: str = "1.0.0"
    ) -> tuple[EvaluationSuite, EvaluationDataset, GateProfile]:
        suite = self.suite(suite_id, version)
        dataset = self.dataset(suite.dataset_id, suite.dataset_version)
        profile = self.gate_profile(suite.gate_profile_id, suite.gate_profile_version)
        if dataset.agent_name not in suite.suite_id:
            raise ValueError("Evaluation suite and dataset agent do not match")
        return suite, dataset, profile

    @staticmethod
    def hash_model(model: BaseModel) -> str:
        return artifact_hash(model.model_dump(mode="json"))

    def _load(
        self,
        kind: str,
        identifier: str,
        version: str,
        model_type: type[ModelT],
    ) -> ModelT:
        path = self._root / kind / f"{identifier}-v{version.split('.')[0]}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Evaluation {kind[:-1]} was not found: {identifier}@{version}")
        model = model_type.model_validate_json(path.read_text())
        actual_version = cast(str, model.model_dump()["version"])
        if actual_version != version:
            raise ValueError(
                f"Evaluation {kind[:-1]} version mismatch: requested {version}, "
                f"found {actual_version}"
            )
        return model
