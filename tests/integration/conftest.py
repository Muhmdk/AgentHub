"""PostgreSQL fixtures that are mandatory when CI supplies a database URL."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from packages.registry.database import Database

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[Database]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("PostgreSQL integration tests require AGENTHUB_DATABASE_URL")

    alembic = Config(ROOT / "alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic, "head")
    database = Database(database_url)
    assert database.ping()
    yield database
    database.dispose()


@pytest.fixture
def registry_database(migrated_database: Database) -> Iterator[Database]:
    with migrated_database.engine.begin() as connection:
        connection.execute(text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE"))
    yield migrated_database
    with migrated_database.engine.begin() as connection:
        connection.execute(text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE"))
