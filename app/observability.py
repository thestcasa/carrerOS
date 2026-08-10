from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_EXTRA_FIELDS = (
    "application_id",
    "correlation_id",
    "duration_ms",
    "event",
    "exception_type",
    "http_method",
    "http_route",
    "processed",
    "role",
    "status_code",
    "task_id",
    "worker_id",
    "workflow_state",
)


def correlation_id(supplied: str | None) -> str:
    """Accept a bounded opaque request ID or create a fresh non-secret identifier."""

    if supplied is not None and _CORRELATION_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


class JsonLogFormatter(logging.Formatter):
    """Small stdlib JSON formatter that emits only explicitly allowlisted metadata."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None and isinstance(value, str | int | float | bool):
                payload[field] = value
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def configure_structured_logging(*, level: int = logging.INFO) -> logging.Logger:
    """Configure the Career OS logger once without changing dependency loggers."""

    logger = logging.getLogger("careeros")
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, "name", None) == "careeros-json" for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.name = "careeros-json"
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    return logger


def event_fields(**values: Any) -> dict[str, object]:
    """Return only safe scalar fields accepted by the structured formatter."""

    return {
        key: value
        for key, value in values.items()
        if key in _EXTRA_FIELDS and isinstance(value, str | int | float | bool)
    }
