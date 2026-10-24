"""Browser decision mapping stays executable without a JavaScript package manager."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.contract
def test_walkthrough_decision_interpretations() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; browser decision tests require node")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/js/demo-decisions.test.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
