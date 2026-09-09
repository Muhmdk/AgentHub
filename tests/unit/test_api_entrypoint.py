"""Unit tests for the configured API process entry point."""

from typing import Any

import pytest

from apps.api import __main__ as api_entrypoint
from apps.api.config import load_settings


@pytest.mark.unit
def test_entrypoint_passes_validated_network_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    load_settings.cache_clear()
    monkeypatch.setenv("AGENTHUB_API_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENTHUB_API_PORT", "8123")
    monkeypatch.setattr(api_entrypoint.uvicorn, "run", fake_run)
    try:
        api_entrypoint.main()
    finally:
        load_settings.cache_clear()

    assert captured == {
        "app": "apps.api.main:app",
        "host": "0.0.0.0",
        "port": 8123,
        "log_config": None,
    }
