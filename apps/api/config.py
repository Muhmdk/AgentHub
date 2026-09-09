"""Typed application configuration loaded from the environment."""

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


def installed_version() -> str:
    """Return the installed package version without making startup depend on packaging."""
    try:
        return version("agenthub")
    except PackageNotFoundError:
        return "0.1.0"


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
    version: str = Field(default_factory=installed_version, min_length=1, max_length=64)


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
