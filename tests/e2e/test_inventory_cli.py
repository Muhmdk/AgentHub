"""End-to-end test for the documented Inventory Agent CLI."""

import json
import subprocess

import pytest


@pytest.mark.e2e
def test_inventory_cli_outputs_machine_readable_evidence() -> None:
    completed = subprocess.run(
        [".venv/bin/python", "-m", "agents.inventory", "--seed", "23"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    body = json.loads(completed.stdout)
    assert "Queen Street may run low" in body["answer"]
    assert body["model"] == "fake/deterministic-v1"
    assert len(body["tool_calls"]) == 4
    assert len(body["citations"]) == 6
