from __future__ import annotations

import json
import logging

from app.observability import JsonLogFormatter, correlation_id, event_fields


def test_json_log_formatter_emits_only_allowlisted_operational_metadata() -> None:
    record = logging.LogRecord(
        "careeros.test",
        logging.INFO,
        __file__,
        1,
        "workflow_complete",
        (),
        None,
    )
    record.correlation_id = "fixture-request-0001"
    record.application_id = "00000000-0000-0000-0000-000000000111"
    record.workflow_state = "confirmed"
    record.secret = "must-not-appear"

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "workflow_complete"
    assert payload["correlation_id"] == "fixture-request-0001"
    assert payload["application_id"] == "00000000-0000-0000-0000-000000000111"
    assert payload["workflow_state"] == "confirmed"
    assert "secret" not in payload


def test_observability_helpers_reject_unbounded_or_unsafe_values() -> None:
    assert correlation_id("fixture-request-0002") == "fixture-request-0002"
    assert len(correlation_id("invalid value")) == 32
    assert event_fields(event="safe", token="never", duration_ms=12.5) == {
        "event": "safe",
        "duration_ms": 12.5,
    }
