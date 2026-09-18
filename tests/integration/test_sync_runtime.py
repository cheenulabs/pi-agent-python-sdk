"""Run the same real-Pi settlement and cancellation behavior through the facade."""

import threading

import pytest

from pi_agent import PiClient, PiRunOwnershipError

from .control import set_responses

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["run", "stream"])
@pytest.mark.parametrize("prompt", ["ordinary input", "/fixture-await-run"])
def test_sync_long_extension_run_before_acknowledgement(pi_options, operation, prompt):
    pi_options["env"]["PI_FIXTURE_TOKENS_PER_SECOND"] = "1500"
    with PiClient(**pi_options) as pi:
        text = "x " * 10000
        set_responses(pi, [{"text": text}])
        if operation == "run":
            result = pi.run(prompt, timeout=30)
        else:
            with pi.stream(prompt, timeout=30) as stream:
                events = list(stream)
                result = stream.result()
            assert len(events) > pi.limits.event_queue_size
            assert "".join(event.text_delta or "" for event in events) == text
        assert result.text == text
        set_responses(pi, [{"text": "next answer"}])
        assert pi.run("ordinary input", timeout=10).text == "next answer"


def test_sync_dialog_deadline_does_not_wait_for_blocked_callback(pi_options):
    release = threading.Event()
    finished = threading.Event()

    def handler(request):
        if request["method"] == "confirm":
            try:
                release.wait(10)
                return True
            finally:
                finished.set()

    try:
        with PiClient(**pi_options, ui_handler=handler) as pi:
            set_responses(pi, [{"text": "answer after expiry"}])
            assert pi.run("fixture timeout during", timeout=5).text == "answer after expiry"
            release.set()
            assert finished.wait(5)
            set_responses(pi, [{"text": "next answer"}])
            assert pi.run("ordinary input", timeout=5).text == "next answer"
    finally:
        release.set()


def test_sync_low_level_input_prevents_owned_runs(pi_options):
    with PiClient(**pi_options) as pi:
        pi.prompt("fixture handled")
        assert not pi.get_state()["isStreaming"]
        with pytest.raises(PiRunOwnershipError):
            pi.run("must use a fresh process")


def test_sync_tools_retry_and_stream_settlement(pi_options):
    with PiClient(**pi_options) as pi:
        set_responses(
            pi,
            [
                {"tool": "fixture_echo", "arguments": {"text": "synthetic echo"}},
                {"stopReason": "error", "error": "overloaded_error"},
                {"thinking": "synthetic reasoning", "text": "recovered sync answer"},
            ],
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
        set_responses(
            pi,
            [
                {
                    "tool": "fixture_echo",
                    "arguments": {"text": "waiting", "wait": "sync-cancel"},
                },
            ],
        )
        with pi.stream("synthetic input", timeout=10) as stream:
            for event in stream:
                if event.type == "tool_execution_update":
                    pi.follow_up("discard this queued input")
                    break
        assert pi.running and not pi.busy
        assert pi.get_state()["pendingMessageCount"] == 0
        set_responses(pi, [{"text": "ready again"}])
        assert pi.run("next input", timeout=10).text == "ready again"
