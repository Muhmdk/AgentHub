"""Process-level evaluation CLI success and release-blocking behavior."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text

from packages.registry.database import Database

ROOT = Path(__file__).parents[2]


@pytest.fixture
def evaluation_database() -> Iterator[Database]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("Evaluation CLI E2E requires AGENTHUB_DATABASE_URL")
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


def command(database: Database, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["AGENTHUB_DATABASE_URL"] = database.engine.url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "packages.evaluation", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


@pytest.mark.e2e
@pytest.mark.integration
def test_cli_emits_passing_json_and_failing_junit(evaluation_database: Database) -> None:
    passing = command(evaluation_database, "--agent", "knowledge-agent")
    failed = command(
        evaluation_database,
        "--agent",
        "knowledge-agent",
        "--candidate-profile",
        "regressed",
        "--format",
        "junit",
    )

    assert passing.returncode == 0
    report = json.loads(passing.stdout)
    assert report["gate"]["passed"] is True
    assert len(report["case_results"]) == 3
    assert len(report["artifact_hash"]) == 64
    replayed = command(
        evaluation_database,
        "--replay-run-id",
        report["run_id"],
    )
    assert replayed.returncode == 0
    assert json.loads(replayed.stdout) == report

    assert failed.returncode == 2
    junit = fromstring(failed.stdout)
    assert junit.tag == "testsuite"
    assert int(junit.attrib["failures"]) > 0
    assert junit.find("./properties/property[@name='artifact_hash']") is not None
