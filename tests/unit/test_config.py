"""Unit tests for safe environment configuration."""

import pytest
from pydantic import ValidationError

from apps.api.config import ConfigurationError, Settings, load_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    load_settings.cache_clear()


@pytest.mark.unit
def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTHUB_DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.model_provider == "fake"
    assert settings.retrieval_provider == "local"
    assert settings.agent_max_steps == 3
    assert settings.rag_top_k == 3
    assert settings.rag_minimum_score == 0.15
    assert settings.retrieval_timeout_seconds == 5.0
    assert settings.database_auth_mode == "password"
    assert settings.database_url.endswith("@127.0.0.1:5433/agenthub")


@pytest.mark.unit
def test_selected_azure_providers_require_coordinates() -> None:
    with pytest.raises(ValidationError, match="Azure OpenAI endpoint and deployment"):
        Settings(model_provider="azure-openai", _env_file=None)
    with pytest.raises(ValidationError, match="Azure Search endpoint and index name"):
        Settings(retrieval_provider="azure-search", _env_file=None)


@pytest.mark.unit
def test_azure_provider_coordinates_are_accepted() -> None:
    settings = Settings(
        model_provider="azure-openai",
        retrieval_provider="azure-search",
        azure_openai_endpoint="https://agenthub.openai.azure.com",
        azure_openai_deployment="gpt-test",
        azure_search_endpoint="https://agenthub.search.windows.net",
        azure_search_index_name="agenthub-chunks-v1",
        _env_file=None,
    )

    assert settings.azure_openai_deployment == "gpt-test"
    assert settings.azure_search_index_name == "agenthub-chunks-v1"


@pytest.mark.unit
def test_azure_database_authentication_requires_psycopg_url() -> None:
    with pytest.raises(ValidationError, match="Azure PostgreSQL requires"):
        Settings(
            database_auth_mode="azure-workload-identity",
            database_url="sqlite:///agenthub.db",
            _env_file=None,
        )


@pytest.mark.unit
def test_azure_monitor_export_requires_connection_coordinates() -> None:
    with pytest.raises(ValidationError, match="Azure Monitor connection string is required"):
        Settings(otel_enabled=True, otel_exporter="azure-monitor", _env_file=None)

    settings = Settings(
        otel_enabled=True,
        otel_exporter="azure-monitor",
        azure_monitor_connection_string=(
            "InstrumentationKey=00000000-0000-0000-0000-000000000005;"
            "IngestionEndpoint=https://canadacentral-0.in.applicationinsights.azure.com/"
        ),
        _env_file=None,
    )
    assert settings.otel_exporter == "azure-monitor"


@pytest.mark.unit
def test_settings_load_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTHUB_ENVIRONMENT", "test")
    monkeypatch.setenv("AGENTHUB_API_PORT", "9000")

    settings = load_settings()

    assert settings.environment == "test"
    assert settings.api_port == 9000


@pytest.mark.unit
def test_invalid_configuration_names_field_without_echoing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_value = "sensitive-invalid-value"
    monkeypatch.setenv("AGENTHUB_API_PORT", invalid_value)

    with pytest.raises(ConfigurationError) as raised:
        load_settings()

    assert "api_port" in str(raised.value)
    assert invalid_value not in str(raised.value)
