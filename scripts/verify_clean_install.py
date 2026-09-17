"""Build and import the AgentHub wheel in a fresh, locked virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    uv = Path(sys.executable).with_name("uv")
    if not uv.is_file():
        raise RuntimeError("Locked uv executable is unavailable; run make setup first")

    with tempfile.TemporaryDirectory(prefix="agenthub-clean-install-") as temporary:
        workspace = Path(temporary)
        distribution = workspace / "dist"
        environment = workspace / "venv"
        run([str(uv), "build", "--wheel", "--out-dir", str(distribution), str(ROOT)])

        sync_environment = os.environ.copy()
        sync_environment["UV_PROJECT_ENVIRONMENT"] = str(environment)
        run(
            [str(uv), "sync", "--project", str(ROOT), "--frozen", "--no-dev", "--inexact"],
            env=sync_environment,
        )
        wheel = next(distribution.glob("agenthub-*.whl"))
        python = environment / "bin/python"
        run(
            [
                str(uv),
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--force-reinstall",
                str(wheel),
            ]
        )
        probe = """
from importlib.metadata import version
from importlib.resources import files
from apps.api.main import create_app

assert version("agenthub")
assert (files("apps.web") / "registry.html").is_file()
assert (files("apps.web") / "assets" / "agenthub.css").is_file()
assert (files("apps.web") / "assets" / "demo.js").is_file()
assert (files("data") / "synthetic" / "corpus.json").is_file()
assert (files("data") / "manifests" / "inventory-agent-v1.json").is_file()
assert any(getattr(route, "path", None) == "/health/live" for route in create_app().routes)
print(f"Clean wheel import passed for AgentHub {version('agenthub')}")
"""
        run([str(python), "-c", probe], cwd=workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
