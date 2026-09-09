"""Unit tests for safe environment configuration."""

import pytest

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
    assert settings.agent_max_steps == 3
    assert settings.rag_top_k == 3
    assert settings.rag_minimum_score == 0.15
    assert settings.retrieval_timeout_seconds == 5.0
    assert settings.database_url.endswith("@127.0.0.1:5433/agenthub")


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
