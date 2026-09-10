"""Explicit provider selection and shared credential lifecycle."""

from dataclasses import dataclass
from typing import Literal, Protocol

from agents.shared.azure import (
    AccessTokenProvider,
    AzureOpenAIChatModel,
    AzureOpenAIConfig,
    AzureSearchConfig,
    AzureSearchRetriever,
    DefaultAzureTokenProvider,
)
from agents.shared.corpus import create_retail_retriever, load_retail_corpus
from agents.shared.model import ChatModel, DeterministicFakeModel
from agents.shared.retrieval import Retriever
from packages.contracts.retrieval import CorpusVersion
from packages.registry.database import Database


class ProviderSettings(Protocol):
    """Configuration fields needed to compose model and retrieval adapters."""

    model_provider: Literal["fake", "azure-openai"]
    retrieval_provider: Literal["local", "azure-search"]
    database_auth_mode: Literal["password", "azure-workload-identity"]
    azure_managed_identity_client_id: str | None
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    azure_openai_token_scope: str
    azure_openai_input_cost_per_million: float
    azure_openai_output_cost_per_million: float
    azure_search_endpoint: str | None
    azure_search_index_name: str | None
    azure_search_api_version: str
    azure_search_token_scope: str
    azure_request_timeout_seconds: float
    azure_postgres_token_scope: str
    database_url: str


@dataclass(frozen=True)
class ProviderBundle:
    """Runtime adapters sharing one lazily evaluated Azure credential chain."""

    model: ChatModel
    retriever: Retriever
    corpus: CorpusVersion
    token_provider: AccessTokenProvider | None = None

    def close(self) -> None:
        if self.token_provider is not None:
            self.token_provider.close()


def create_chat_model(
    provider: str,
    *,
    azure_config: AzureOpenAIConfig | None = None,
    token_provider: AccessTokenProvider | None = None,
) -> ChatModel:
    """Create a configured model adapter without implicit network fallbacks."""
    if provider == "fake":
        return DeterministicFakeModel()
    if provider == "azure-openai" and azure_config is not None and token_provider is not None:
        return AzureOpenAIChatModel(azure_config, token_provider)
    raise ValueError("Unsupported model provider")


def create_provider_bundle(settings: ProviderSettings) -> ProviderBundle:
    """Compose explicit local or Azure adapters from validated settings."""
    uses_azure = (
        settings.model_provider == "azure-openai"
        or settings.retrieval_provider == "azure-search"
        or settings.database_auth_mode == "azure-workload-identity"
    )
    token_provider: AccessTokenProvider | None = None
    if uses_azure:
        token_provider = DefaultAzureTokenProvider(settings.azure_managed_identity_client_id)

    try:
        azure_model_config = None
        if settings.model_provider == "azure-openai":
            if settings.azure_openai_endpoint is None or settings.azure_openai_deployment is None:
                raise ValueError("Azure OpenAI settings are incomplete")
            azure_model_config = AzureOpenAIConfig(
                endpoint=settings.azure_openai_endpoint,
                deployment=settings.azure_openai_deployment,
                token_scope=settings.azure_openai_token_scope,
                timeout_seconds=settings.azure_request_timeout_seconds,
                input_cost_per_million=settings.azure_openai_input_cost_per_million,
                output_cost_per_million=settings.azure_openai_output_cost_per_million,
            )
        model = create_chat_model(
            settings.model_provider,
            azure_config=azure_model_config,
            token_provider=token_provider,
        )

        retriever: Retriever
        if settings.retrieval_provider == "local":
            retriever, corpus, _ = create_retail_retriever()
        elif (
            settings.retrieval_provider == "azure-search"
            and settings.azure_search_endpoint is not None
            and settings.azure_search_index_name is not None
            and token_provider is not None
        ):
            corpus, _ = load_retail_corpus()
            retriever = AzureSearchRetriever(
                AzureSearchConfig(
                    endpoint=settings.azure_search_endpoint,
                    index_name=settings.azure_search_index_name,
                    api_version=settings.azure_search_api_version,
                    token_scope=settings.azure_search_token_scope,
                    timeout_seconds=settings.azure_request_timeout_seconds,
                ),
                token_provider,
            )
        else:
            raise ValueError("Unsupported retrieval provider")
    except Exception:
        if token_provider is not None:
            token_provider.close()
        raise
    return ProviderBundle(model, retriever, corpus, token_provider)


def create_database(settings: ProviderSettings, bundle: ProviderBundle) -> Database:
    """Compose PostgreSQL with a fresh Entra token for every pooled connection."""
    if settings.database_auth_mode == "password":
        return Database(settings.database_url)
    if bundle.token_provider is None:
        raise ValueError("Azure PostgreSQL authentication requires an Azure token provider")
    return Database(
        settings.database_url,
        token_provider=bundle.token_provider,
        token_scope=settings.azure_postgres_token_scope,
    )
