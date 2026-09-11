"""Chat-model ports and a deterministic local adapter."""

import hashlib
from typing import Protocol

from packages.contracts.runtime import ModelRequest, ModelResponse, Usage


class ChatModel(Protocol):
    """Small provider-neutral model boundary used by agent graphs."""

    @property
    def name(self) -> str:
        """Return a stable provider/model identifier."""
        ...

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one bounded completion."""
        ...


class RetryableModelError(RuntimeError):
    """Sanitized transient provider failure eligible for a bounded retry."""


class DeterministicFakeModel:
    """Offline model that deterministically returns a prepared answer prompt."""

    name = "fake/deterministic-v1"
    _ANSWER_PREFIX = "FINAL_ANSWER:\n"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        canonical_request = request.model_dump_json(exclude_none=True)
        response_id = hashlib.sha256(canonical_request.encode()).hexdigest()[:16]
        last_message = request.messages[-1].content
        content = (
            last_message.removeprefix(self._ANSWER_PREFIX)
            if last_message.startswith(self._ANSWER_PREFIX)
            else f"Deterministic response: {last_message}"
        )
        return ModelResponse(
            response_id=f"fake-{response_id}",
            model=self.name,
            content=content,
            usage=Usage(
                input_tokens=self._estimate_tokens(canonical_request),
                output_tokens=self._estimate_tokens(content),
            ),
        )

    @staticmethod
    def _estimate_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)
