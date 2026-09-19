"""Check public conveniences and the pinned discovery-to-type coverage contract."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, NotRequired, get_args, get_origin, get_type_hints

import pytest

from pi_agent import types
from pi_agent.errors import (
    PiCommandError,
    PiProtocolError,
    PiRunError,
    PiTimeoutError,
)
from pi_agent.types import Event, Limits, RunResult, SessionInfo, UsageSummary


def test_event_preserves_unknown_fields_without_dumping_them() -> None:
    raw = {"type": "future_event", "provider_metadata": {"secret": "private-value"}}
    event = Event(raw)
    assert event.raw is raw
    assert event.type == "future_event"
    assert event.text_delta is None
    assert "private-value" not in repr(event)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": ""},
            },
            "",
        ),
        (
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "a\u2028b"},
            },
            "a\u2028b",
        ),
        (
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "thinking_delta", "delta": "x"},
            },
            None,
        ),
        ({"type": "message_update", "assistantMessageEvent": None}, None),
        (
            {"type": "message_end", "assistantMessageEvent": {"type": "text_delta", "delta": "x"}},
            None,
        ),
    ],
)
def test_text_delta_uses_only_the_wire_text_update(
    raw: dict[str, Any], expected: str | None
) -> None:
    assert Event(raw).text_delta == expected


def test_result_and_exceptions_do_not_dump_content() -> None:
    session = SessionInfo("id", "/private/session", "private-name")
    result = RunResult("private-answer", [{"content": "private-answer"}], "error", session, 0.1)
    assert "private" not in repr(result)
    assert result.text == "private-answer"
    assert PiRunError("Run failed", result).result is result
    error = PiCommandError("prompt", "private-error", "request-1")
    assert error.error == "private-error"
    assert error.request_id == "request-1"
    assert "private-error" not in str(error)
    assert "private-error" not in repr(error)


@pytest.mark.parametrize("delta", [None, 3, False, {}, []])
def test_malformed_known_text_delta_is_reported(delta: Any) -> None:
    with pytest.raises(PiProtocolError, match="text_delta"):
        _ = Event(
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": delta,
                },
            }
        ).text_delta


def test_usage_defaults_are_unknown_and_snapshot_fields_are_frozen() -> None:
    summary = UsageSummary()
    assert summary.input_tokens is None
    assert summary.cost is None
    assert summary.assistant_messages == 0
    with pytest.raises(FrozenInstanceError):
        summary.cost = 0.0  # type: ignore[misc]


def test_timeout_retains_uncertainty_metadata() -> None:
    error = PiTimeoutError("Deadline", "prompt", "request-1")
    assert isinstance(error, TimeoutError)
    assert error.uncertain
    assert error.command == "prompt"
    assert error.request_id == "request-1"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, None, "30"])
@pytest.mark.parametrize(
    "name", ["startup_timeout", "command_timeout", "run_start_timeout", "cleanup_timeout"]
)
def test_limits_reject_invalid_deadlines(name: str, value: Any) -> None:
    with pytest.raises(ValueError, match=name):
        Limits(**{name: value})


@pytest.mark.parametrize("value", [0, -1, 1.5, True, None])
@pytest.mark.parametrize(
    "name",
    [
        "max_record_bytes",
        "event_queue_size",
        "event_queue_bytes",
        "result_message_count",
        "collection_event_count",
        "collection_event_bytes",
        "result_message_bytes",
    ],
)
def test_limits_require_positive_integer_capacities(name: str, value: Any) -> None:
    with pytest.raises(ValueError, match=name):
        Limits(**{name: value})


def test_stderr_can_be_disabled_but_not_negative() -> None:
    assert Limits().stderr_tail_bytes == 0
    assert Limits(stderr_tail_bytes=10).stderr_tail_bytes == 10
    with pytest.raises(ValueError, match="stderr_tail_bytes"):
        Limits(stderr_tail_bytes=-1)


def _discriminators(union: Any, field: str) -> set[str]:
    return {
        value for variant in get_args(union) for value in get_args(get_type_hints(variant)[field])
    }


def _table_rows(discovery: str, heading: str) -> set[str]:
    section = discovery.split(heading, 1)[1].split("\n##", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("| ")]
    return {line.split("|")[1].strip() for line in lines[1:]}


def test_wire_unions_cover_the_discovered_protocol() -> None:
    discovery = (Path(__file__).parents[1] / "docs" / "discovery.md").read_text(encoding="utf-8")
    commands = _table_rows(discovery, "## Complete command coverage")
    events = _table_rows(discovery, "## Complete output event surface")
    nested = _table_rows(discovery, "### Nested assistant events")
    ui = _table_rows(discovery, "### Extension UI\n")
    entries = _table_rows(discovery, "### Session entries and tree")
    assert _discriminators(types.RpcCommand, "type") == commands
    assert _discriminators(types.SessionEvent, "type") == events - {
        "extension_error",
        "extension_ui_request",
    }
    assert _discriminators(types.AssistantMessageEvent, "type") == nested
    assert _discriminators(types.ExtensionUIRequest, "method") == ui
    assert _discriminators(types.SessionEntry, "type") == entries
    assert len(commands) == 33
    assert len(events) == 25
    assert len(nested) == 12
    assert len(ui) == 9
    assert len(entries) == 9
    assert _discriminators(types.AgentMessage, "role") == {
        "user",
        "assistant",
        "toolResult",
        "bashExecution",
        "custom",
        "branchSummary",
        "compactionSummary",
    }


def test_annotations_preserve_runtime_omission_and_wire_serialization() -> None:
    assert get_origin(get_type_hints(types.ForkResult, include_extras=True)["text"]) is NotRequired
    assert (
        get_origin(get_type_hints(types.UISetStatusRequest, include_extras=True)["statusText"])
        is NotRequired
    )
    assert "message" not in get_type_hints(types.MessageUpdateEvent)
    for variant in get_args(types.AssistantMessageEvent):
        assert "partial" not in get_type_hints(variant)
