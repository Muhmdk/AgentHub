"""Explicit model-provider selection for local agent composition."""

from agents.shared.model import ChatModel, DeterministicFakeModel


def create_chat_model(provider: str) -> ChatModel:
    """Create a configured model adapter without implicit network fallbacks."""
    if provider == "fake":
        return DeterministicFakeModel()
    raise ValueError("Unsupported model provider")
