"""Run the same real-Pi settlement and cancellation behavior through the facade."""

import json

import pytest

from pi_coding_agent_client import PiClient

pytestmark = pytest.mark.integration


def test_sync_tools_retry_and_stream_settlement(pi_options):
    with PiClient(**pi_options) as pi:
        pi.prompt(
            "/fixture-script "
            + json.dumps(
                [
                    {"tool": "fixture_echo", "arguments": {"text": "synthetic echo"}},
                    {"stopReason": "error", "error": "overloaded_error"},
                    {"thinking": "synthetic reasoning", "text": "recovered sync answer"},
                ]
            )
        )
        with pi.stream("synthetic input", timeout=10) as stream:
            events = list(stream)
            result = stream.result()
        assert result.text == "recovered sync answer"
        assert {"tool_execution_start", "auto_retry_start", "agent_settled"}.issubset(
            {event.type for event in events}
        )
        assert result.usage.assistant_messages == 3
        assert result.session.session_id == pi.get_state()["sessionId"]


def test_sync_stream_exit_clears_queued_work_and_is_reusable(pi_options):
    with PiClient(**pi_options) as pi:
        pi.prompt(
            "/fixture-script "
            + json.dumps(
                [
                    {
                        "tool": "fixture_echo",
                        "arguments": {"text": "waiting", "wait": "sync-cancel"},
                    },
                ]
            )
        )
        with pi.stream("synthetic input", timeout=10) as stream:
            for event in stream:
                if event.type == "tool_execution_update":
                    pi.follow_up("discard this queued input")
                    break
        assert pi.running and not pi.busy
        assert pi.get_state()["pendingMessageCount"] == 0
        pi.prompt('/fixture-script [{"text":"ready again"}]')
        assert pi.run("next input", timeout=10).text == "ready again"
