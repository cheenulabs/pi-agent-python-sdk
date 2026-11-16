"""Only diagnostic kinds/codes, never payloads, belong in debug logs."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from pi_agent.durable import AsyncDurableClient


@pytest.mark.parametrize(
    "record, expected",
    [
        (
            {
                "type": "durable_report",
                "report": {"kind": "task_error", "error": "private-payload"},
            },
            "durable_report task_error",
        ),
        (
            {"type": "durable_report", "report": {"kind": {"secret": "private-payload"}}},
            "durable_report None",
        ),
        (
            {"type": "durable_protocol_error", "code": "bad_request", "message": "private-payload"},
            "durable_protocol_error bad_request",
        ),
    ],
)
def test_diagnostics_log_only_markers(
    caplog: pytest.LogCaptureFixture, record: dict[str, Any], expected: str
) -> None:
    client = AsyncDurableClient(None)
    with caplog.at_level(logging.DEBUG, logger="pi_agent.durable"):
        client._on_event(record)
    assert expected in caplog.text
    assert "private-payload" not in caplog.text
    assert "secret" not in caplog.text
