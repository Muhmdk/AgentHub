"""Fail-closed safety checks for destructive local demo resets."""

import pytest

from apps.api.config import Settings
from packages.registry.database import Database
from scripts.seed_demo import require_safe_demo_database

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_demo_reset_rejects_nonlocal_environments(environment: str) -> None:
    database = Database("postgresql+psycopg://agenthub:agenthub@127.0.0.1:5433/agenthub")
    try:
        with pytest.raises(RuntimeError, match="restricted"):
            require_safe_demo_database(
                Settings(
                    environment=environment,
                    gateway_service_tokens={"service/demo": "x" * 32},
                    policy_engine_url="http://127.0.0.1:8181",
                    _env_file=None,
                ),
                database,
            )
    finally:
        database.dispose()


def test_demo_reset_rejects_nonlocal_database_targets() -> None:
    database = Database("postgresql+psycopg://agenthub:agenthub@db.example/agenthub")
    try:
        with pytest.raises(RuntimeError, match="restricted"):
            require_safe_demo_database(Settings(environment="local", _env_file=None), database)
    finally:
        database.dispose()


def test_demo_reset_rejects_network_providers() -> None:
    database = Database("postgresql+psycopg://agenthub:agenthub@127.0.0.1:5433/agenthub")
    try:
        with pytest.raises(RuntimeError, match="restricted"):
            require_safe_demo_database(
                Settings(
                    environment="local",
                    model_provider="azure-openai",
                    azure_openai_endpoint="https://model.example",
                    azure_openai_deployment="demo",
                    _env_file=None,
                ),
                database,
            )
    finally:
        database.dispose()
