"""Initialize least-privilege AgentHub roles on Azure Database for PostgreSQL."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, make_url, text

from agents.shared.providers import create_database, create_provider_bundle
from apps.api.config import load_settings
from packages.registry.database import Database

ROOT = Path(__file__).parents[2]


def _postgres_database_url(database_url: str) -> str:
    return make_url(database_url).set(database="postgres").render_as_string(hide_password=False)


def _quote_identifier(connection: Connection, value: str) -> str:
    return connection.dialect.identifier_preparer.quote(value)


def ensure_application_principal(
    connection: Connection,
    principal_name: str,
    principal_object_id: UUID,
) -> bool:
    """Create the workload identity's non-admin Entra role exactly once."""
    exists = connection.execute(
        text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role_name"),
        {"role_name": principal_name},
    ).scalar_one_or_none()
    if exists is not None:
        return False
    connection.execute(
        text(
            "SELECT * FROM pg_catalog.pgaadauth_create_principal_with_oid("
            ":role_name, :object_id, 'service', false, false)"
        ),
        {"role_name": principal_name, "object_id": str(principal_object_id)},
    )
    return True


def grant_application_permissions(
    connection: Connection,
    principal_name: str,
    database_name: str,
) -> None:
    """Grant only the connection and DML privileges needed by the API."""
    principal = _quote_identifier(connection, principal_name)
    database = _quote_identifier(connection, database_name)
    statements = (
        f"GRANT CONNECT ON DATABASE {database} TO {principal}",
        f"GRANT USAGE ON SCHEMA public TO {principal}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {principal}",
        f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {principal}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {principal}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {principal}",
    )
    for statement in statements:
        connection.execute(text(statement))


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    command_parser.add_argument(
        "--app-principal-name",
        default=os.getenv("AGENTHUB_DATABASE_APP_PRINCIPAL_NAME"),
    )
    command_parser.add_argument(
        "--app-principal-object-id",
        type=UUID,
        default=os.getenv("AGENTHUB_DATABASE_APP_PRINCIPAL_OBJECT_ID"),
    )
    return command_parser


def main(arguments: Sequence[str] | None = None) -> int:
    command_parser = parser()
    parsed = command_parser.parse_args(arguments)
    if not parsed.app_principal_name or parsed.app_principal_object_id is None:
        command_parser.error("application principal name and object ID are required")

    settings = load_settings()
    if settings.database_auth_mode != "azure-workload-identity":
        command_parser.error("Azure database bootstrap requires workload-identity authentication")
    target_url = make_url(settings.database_url)
    if not target_url.database or target_url.database == "postgres":
        command_parser.error("AGENTHUB_DATABASE_URL must select the application database")

    providers = create_provider_bundle(settings)
    admin_database = create_database(settings, providers)
    postgres_database = Database(
        _postgres_database_url(settings.database_url),
        token_provider=providers.token_provider,
        token_scope=settings.azure_postgres_token_scope,
    )
    try:
        with postgres_database.engine.begin() as connection:
            created = ensure_application_principal(
                connection,
                parsed.app_principal_name,
                parsed.app_principal_object_id,
            )

        alembic_config = Config(str(ROOT / "alembic.ini"))
        with admin_database.engine.begin() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
            grant_application_permissions(
                connection, parsed.app_principal_name, target_url.database
            )
    except Exception as exc:
        print(f"database bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        postgres_database.dispose()
        admin_database.dispose()
        providers.close()

    principal_status = "created" if created else "already existed"
    print(f"Azure PostgreSQL principal {principal_status}; migrations applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
