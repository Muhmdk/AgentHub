"""Process-level pass, block, and retry coverage for the release pipeline."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text

from packages.registry.database import Database

ROOT = Path(__file__).parents[2]


@pytest.fixture
def release_database() -> Iterator[Database]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("Release pipeline E2E requires AGENTHUB_DATABASE_URL")
    alembic = Config(ROOT / "alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(alembic, "head")
    database = Database(database_url)
    with database.engine.begin() as connection:
        connection.execute(text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE"))
    try:
        yield database
    finally:
        with database.engine.begin() as connection:
            connection.execute(
                text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE")
            )
        database.dispose()


def _simulate(database: Database, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["AGENTHUB_DATABASE_URL"] = database.engine.url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "packages.release", "simulate", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


@pytest.mark.e2e
@pytest.mark.integration
def test_release_pipeline_promotes_once_and_replays_without_duplicate_events(
    release_database: Database,
) -> None:
    result = _simulate(release_database, "--pipeline-id", "e2e-release-pass")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "promoted"
    assert payload["release"]["state"] == "production"
    assert payload["idempotency"] == {
        "candidate_created_once": True,
        "same_release_on_retry": True,
        "promotion_replay_preserved_state": True,
        "event_count": 4,
    }


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.parametrize(
    "arguments",
    [
        ("--pipeline-id", "e2e-evaluation-block", "--candidate-profile", "regressed"),
        ("--pipeline-id", "e2e-security-block", "--security-passed", "false"),
    ],
)
def test_release_pipeline_blocks_failed_technical_gates(
    release_database: Database,
    arguments: tuple[str, ...],
) -> None:
    result = _simulate(release_database, *arguments)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["release"]["state"] == "evaluated"
    assert payload["release"]["gate"]["passed"] is False
    assert payload["idempotency"]["event_count"] == 1
    assert payload["blocked_reason"].startswith("Promotion is blocked:")
