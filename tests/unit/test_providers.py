"""Unit tests for explicit model-provider selection."""

import pytest

from agents.shared.model import DeterministicFakeModel
from agents.shared.providers import create_chat_model


@pytest.mark.unit
def test_fake_provider_is_selected_explicitly() -> None:
    assert isinstance(create_chat_model("fake"), DeterministicFakeModel)


@pytest.mark.unit
def test_unknown_provider_does_not_fall_back_to_network() -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_chat_model("unknown")
