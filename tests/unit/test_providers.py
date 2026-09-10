"""Unit tests for explicit model-provider selection."""

import pytest

from agents.shared.azure import (
    AccessTokenProvider,
    AzureOpenAIChatModel,
    AzureOpenAIConfig,
    AzureSearchRetriever,
)
from agents.shared.model import DeterministicFakeModel
from agents.shared.providers import create_chat_model, create_database, create_provider_bundle
from agents.shared.retrieval import InMemoryRetriever
from apps.api.config import Settings


class OfflineTokenProvider(AccessTokenProvider):
    def get_token(self, scope: str) -> str:
        return "offline-token"  # pragma: allowlist secret

    def close(self) -> None:
        pass


@pytest.mark.unit
def test_fake_provider_is_selected_explicitly() -> None:
    assert isinstance(create_chat_model("fake"), DeterministicFakeModel)


@pytest.mark.unit
def test_unknown_provider_does_not_fall_back_to_network() -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_chat_model("unknown")


@pytest.mark.unit
def test_azure_provider_requires_explicit_config_and_token_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_chat_model("azure-openai")

    model = create_chat_model(
        "azure-openai",
        azure_config=AzureOpenAIConfig(
            endpoint="https://agenthub.openai.azure.com",
            deployment="gpt-test",
        ),
        token_provider=OfflineTokenProvider(),
    )

    assert isinstance(model, AzureOpenAIChatModel)


@pytest.mark.unit
def test_local_provider_bundle_remains_offline() -> None:
    bundle = create_provider_bundle(Settings(_env_file=None))

    assert isinstance(bundle.model, DeterministicFakeModel)
    assert isinstance(bundle.retriever, InMemoryRetriever)
    assert bundle.token_provider is None
    bundle.close()


@pytest.mark.unit
def test_azure_provider_bundle_shares_and_closes_token_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfiguredTokenProvider(OfflineTokenProvider):
        def __init__(self, client_id: str | None) -> None:
            self.client_id = client_id
            self.closed = False
            created.append(self)

        def close(self) -> None:
            self.closed = True

    created: list[ConfiguredTokenProvider] = []
    monkeypatch.setattr(
        "agents.shared.providers.DefaultAzureTokenProvider", ConfiguredTokenProvider
    )
    bundle = create_provider_bundle(
        Settings(
            model_provider="azure-openai",
            retrieval_provider="azure-search",
            azure_managed_identity_client_id="workload-client-id",
            azure_openai_endpoint="https://agenthub.openai.azure.com",
            azure_openai_deployment="gpt-test",
            azure_search_endpoint="https://agenthub.search.windows.net",
            azure_search_index_name="agenthub-chunks-v1",
            _env_file=None,
        )
    )

    assert isinstance(bundle.model, AzureOpenAIChatModel)
    assert isinstance(bundle.retriever, AzureSearchRetriever)
    assert bundle.model._token_provider is bundle.retriever._token_provider
    assert created[0].client_id == "workload-client-id"
    bundle.close()
    assert created[0].closed


@pytest.mark.unit
def test_azure_database_authentication_uses_the_shared_token_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfiguredTokenProvider(OfflineTokenProvider):
        def __init__(self, client_id: str | None) -> None:
            self.client_id = client_id

    monkeypatch.setattr(
        "agents.shared.providers.DefaultAzureTokenProvider", ConfiguredTokenProvider
    )
    settings = Settings(
        database_auth_mode="azure-workload-identity",
        database_url="postgresql+psycopg://agenthub@database.example/agenthub",
        azure_managed_identity_client_id="database-client-id",
        _env_file=None,
    )
    bundle = create_provider_bundle(settings)
    database = create_database(settings, bundle)
    try:
        assert database._token_provider is bundle.token_provider
        assert isinstance(bundle.token_provider, ConfiguredTokenProvider)
        assert bundle.token_provider.client_id == "database-client-id"
    finally:
        database.dispose()
        bundle.close()


@pytest.mark.unit
def test_provider_bundle_closes_token_provider_when_composition_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConfiguredTokenProvider(OfflineTokenProvider):
        def __init__(self, client_id: str | None) -> None:
            self.closed = False
            created.append(self)

        def close(self) -> None:
            self.closed = True

    created: list[ConfiguredTokenProvider] = []
    monkeypatch.setattr(
        "agents.shared.providers.DefaultAzureTokenProvider", ConfiguredTokenProvider
    )

    with pytest.raises(ValueError, match="HTTPS"):
        create_provider_bundle(
            Settings(
                model_provider="azure-openai",
                azure_openai_endpoint="http://insecure.example",
                azure_openai_deployment="gpt-test",
                _env_file=None,
            )
        )

    assert created[0].closed
