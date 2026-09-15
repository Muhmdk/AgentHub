"""PostgreSQL connection-pool exhaustion and recovery coverage."""

import time

import pytest
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from packages.registry.database import Database


@pytest.mark.integration
def test_pool_exhaustion_fails_within_bound_and_recovers(migrated_database: Database) -> None:
    database = Database(
        migrated_database.engine.url.render_as_string(hide_password=False),
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=0.1,
    )
    try:
        with database.engine.connect():
            started = time.monotonic()
            with pytest.raises(SQLAlchemyTimeoutError):
                database.ping()
            elapsed = time.monotonic() - started

        assert 0.05 <= elapsed < 1
        assert database.ping()
    finally:
        database.dispose()
