"""Unit tests for the offline deterministic model adapter."""

import asyncio

import pytest
from pydantic import ValidationError

from agents.shared.model import DeterministicFakeModel
from packages.contracts.runtime import ChatMessage, ModelRequest


@pytest.mark.unit
def test_fake_model_replays_identical_seeded_requests() -> None:
    model = DeterministicFakeModel()
    request = ModelRequest(
        messages=[
            ChatMessage(role="system", content="Return only the prepared answer."),
            ChatMessage(role="user", content="FINAL_ANSWER:\nStore A may run low."),
        ],
        seed=17,
    )

    first = asyncio.run(model.generate(request))
    second = asyncio.run(model.generate(request))

    assert first == second
    assert first.content == "Store A may run low."
    assert first.model == "fake/deterministic-v1"
    assert first.usage.input_tokens > 0
    assert first.usage.output_tokens > 0


@pytest.mark.unit
def test_fake_model_seed_changes_replay_identity() -> None:
    model = DeterministicFakeModel()
    message = ChatMessage(role="user", content="hello")

    first = asyncio.run(model.generate(ModelRequest(messages=[message], seed=1)))
    second = asyncio.run(model.generate(ModelRequest(messages=[message], seed=2)))

    assert first.response_id != second.response_id
    assert first.content == second.content == "Deterministic response: hello"


@pytest.mark.unit
def test_model_request_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(messages=[])
