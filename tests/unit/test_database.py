"""Unit tests for passwordless PostgreSQL connection composition."""

from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import Connection

from packages.registry.azure_bootstrap import (
    _postgres_database_url,
    ensure_application_principal,
)
from packages.registry.database import Database


class RotatingTokenSource:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return f"token-{len(self.scopes)}"  # pragma: allowlist secret


@pytest.mark.unit
def test_database_injects_a_fresh_access_token_for_each_connection() -> None:
    tokens = RotatingTokenSource()
    database = Database(
        "sqlite://",
        token_provider=tokens,
        token_scope="https://database.example/.default",
    )
    try:
        first: dict[str, Any] = {}
        second: dict[str, Any] = {}

        database._inject_access_token(None, None, [], first)
        database._inject_access_token(None, None, [], second)

        assert first["password"] == "token-1"  # pragma: allowlist secret
        assert second["password"] == "token-2"  # pragma: allowlist secret
        assert tokens.scopes == [
            "https://database.example/.default",
            "https://database.example/.default",
        ]
    finally:
        database.dispose()


@pytest.mark.unit
def test_azure_bootstrap_targets_postgres_and_creates_principal_by_object_id() -> None:
    assert (
        _postgres_database_url(
            "postgresql+psycopg://identity@db.example:5432/agenthub?sslmode=require"
        )
        == "postgresql+psycopg://identity@db.example:5432/postgres?sslmode=require"
    )

    connection_mock = Mock()
    connection_mock.execute.return_value.scalar_one_or_none.return_value = None
    connection = cast(Connection, connection_mock)
    object_id = UUID("00000000-0000-0000-0000-000000000004")

    created = ensure_application_principal(connection, "id-agenthub", object_id)

    assert created
    create_call = connection_mock.execute.call_args_list[1]
    assert "pgaadauth_create_principal_with_oid" in str(create_call.args[0])
    assert create_call.args[1] == {
        "role_name": "id-agenthub",
        "object_id": str(object_id),
    }


@pytest.mark.unit
def test_azure_bootstrap_reuses_existing_principal() -> None:
    connection_mock = Mock()
    connection_mock.execute.return_value.scalar_one_or_none.return_value = 1
    connection = cast(Connection, connection_mock)

    created = ensure_application_principal(
        connection,
        "id-agenthub",
        UUID("00000000-0000-0000-0000-000000000004"),
    )

    assert not created
    assert connection_mock.execute.call_count == 1
