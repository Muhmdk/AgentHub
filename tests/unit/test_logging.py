"""Unit tests for structured logging and correlation IDs."""

import json
import logging

import pytest

from apps.api.config import Settings
from apps.api.logging import JsonFormatter, correlation_id_context
from apps.api.middleware import normalize_correlation_id


@pytest.mark.unit
def test_json_formatter_emits_operational_fields() -> None:
    formatter = JsonFormatter(Settings(environment="test", _env_file=None))
    record = logging.LogRecord(
        name="agenthub.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.status_code = 200
    token = correlation_id_context.set("corr-test-1")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        correlation_id_context.reset(token)

    assert payload["level"] == "INFO"
    assert payload["service"] == "agenthub-api"
    assert payload["environment"] == "test"
    assert payload["correlation_id"] == "corr-test-1"
    assert payload["message"] == "request_completed"
    assert payload["status_code"] == 200
    assert payload["timestamp"].endswith("+00:00")


@pytest.mark.unit
def test_correlation_id_accepts_safe_values_and_replaces_unsafe_values() -> None:
    assert normalize_correlation_id("client.request:42") == "client.request:42"

    generated = normalize_correlation_id("unsafe value\nforged-log")

    assert generated != "unsafe value\nforged-log"
    assert len(generated) == 36
