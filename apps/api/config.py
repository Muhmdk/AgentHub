"""Typed application configuration loaded from the environment."""

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agents.shared.azure import (
    AZURE_OPENAI_SCOPE,
    AZURE_SEARCH_API_VERSION,
    AZURE_SEARCH_SCOPE,
)


def installed_version() -> str:
    """Return the installed package version without making startup depend on packaging."""
    try:
        return version("agenthub")
    except PackageNotFoundError:
        return "0.3.0"


class Settings(BaseSettings):
    """AgentHub runtime settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTHUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = Field(default="agenthub-api", min_length=1, max_length=64)
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    model_provider: Literal["fake", "azure-openai"] = "fake"
    retrieval_provider: Literal["local", "azure-search"] = "local"
    azure_managed_identity_client_id: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_token_scope: str = Field(default=AZURE_OPENAI_SCOPE, min_length=1)
    azure_openai_input_cost_per_million: float = Field(default=0.0, ge=0.0)
    azure_openai_output_cost_per_million: float = Field(default=0.0, ge=0.0)
    azure_search_endpoint: str | None = None
    azure_search_index_name: str | None = None
    azure_search_api_version: str = Field(default=AZURE_SEARCH_API_VERSION, min_length=1)
    azure_search_token_scope: str = Field(default=AZURE_SEARCH_SCOPE, min_length=1)
    azure_request_timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    database_auth_mode: Literal["password", "azure-workload-identity"] = "password"
    azure_postgres_token_scope: str = Field(
        default="https://ossrdbms-aad.database.windows.net/.default",
        min_length=1,
    )
    agent_max_steps: int = Field(default=3, ge=1, le=20)
    tool_timeout_seconds: float = Field(default=1.0, gt=0.0, le=30.0)
    agent_timeout_seconds: float = Field(default=5.0, gt=0.0, le=120.0)
    rag_top_k: int = Field(default=3, ge=1, le=20)
    rag_minimum_score: float = Field(default=0.15, ge=0.0, le=1.0)
    retrieval_timeout_seconds: float = Field(default=5.0, gt=0.0, le=120.0)
    otel_enabled: bool = False
    otel_endpoint: str = Field(default="http://127.0.0.1:4318", min_length=1, max_length=500)
    otel_export_interval_ms: int = Field(default=5000, ge=100, le=60000)
    otel_max_queue_size: int = Field(default=256, ge=64, le=4096)
    observability_grafana_url: str = Field(
        default="http://127.0.0.1:3000",
        min_length=1,
        max_length=500,
    )
    database_url: str = Field(
        default="postgresql+psycopg://agenthub:agenthub@127.0.0.1:5433/agenthub",
        min_length=1,
    )
    version: str = Field(default_factory=installed_version, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_selected_providers(self) -> Self:
        """Require Azure coordinates only when a network provider is selected."""
        if self.model_provider == "azure-openai" and (
            not self.azure_openai_endpoint or not self.azure_openai_deployment
        ):
            raise ValueError("Azure OpenAI endpoint and deployment are required")
        if self.retrieval_provider == "azure-search" and (
            not self.azure_search_endpoint or not self.azure_search_index_name
        ):
            raise ValueError("Azure Search endpoint and index name are required")
        if (
            self.database_auth_mode == "azure-workload-identity"
            and not self.database_url.startswith("postgresql+psycopg://")
        ):
            raise ValueError("Azure PostgreSQL requires a psycopg SQLAlchemy URL")
        return self


class ConfigurationError(RuntimeError):
    """Safe startup error that identifies invalid fields without echoing values."""


@lru_cache
def load_settings() -> Settings:
    """Load and validate settings once for the process."""
    try:
        return Settings()
    except ValidationError as exc:
        issues = []
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            issues.append(f"{location} ({error['type']})")
        raise ConfigurationError(f"Invalid AgentHub configuration: {', '.join(issues)}") from None
