"""JSON logging and request-correlation support."""

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any, override

from apps.api.config import Settings

correlation_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="unavailable"
)

_STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Serialize log records with a stable operational envelope."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._service = settings.service_name
        self._environment = settings.environment

    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "environment": self._environment,
            "correlation_id": correlation_id_context.get(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    """Configure application logs without exposing request content."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(settings))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)
