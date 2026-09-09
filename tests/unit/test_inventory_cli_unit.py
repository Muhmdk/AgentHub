"""Unit tests for Inventory Agent CLI behavior."""

import json

import pytest

from agents.inventory.__main__ import main


@pytest.mark.unit
def test_cli_runs_default_demo(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--seed", "5", "--as-of", "2026-09-08"])

    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert exit_code == 0
    assert "Queen Street may run low" in response["answer"]
    assert captured.err == ""


@pytest.mark.unit
def test_cli_returns_stable_error_for_unsupported_question(
    capsys: pytest.CaptureFixture[str],
) -> None:
    unknown = "sensitive-unknown-place"

    exit_code = main([f"Will shovels run low in {unknown}?"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "invalid_request: Ask about a supported city and product\n"
    assert unknown not in captured.err
