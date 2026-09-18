"""Observable async client behavior against a deterministic executable."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from pi_agent.client import AsyncPiClient
from pi_agent.errors import (
    PiBusyError,
    PiCommandError,
    PiProcessError,
    PiProtocolError,
    PiResultOverflow,
    PiRunError,
    PiRunOwnershipError,
    PiRunStartTimeout,
    PiSubscriptionOverflow,
    PiTimeoutError,
    PiUIHandlerError,
)
from pi_agent.types import Limits

FAKE = Path(__file__).with_name("fake_client_pi.py")


async def test_elapsed_time_excludes_state_preflight_and_final_refresh():
    async with AsyncPiClient(executable=[sys.executable, str(FAKE), "--slow-state"]) as pi:
        before = time.monotonic()
        result = await pi.run("normal")
        duration = time.monotonic() - before
        assert duration - result.elapsed_seconds >= 0.18


@pytest.mark.parametrize("raw", [False, True])
async def test_unowned_submission_permanently_prevents_owned_run(client, raw):
    if raw:
        await client.request("prompt", message="handled")
    else:
        await client.prompt("handled")
    assert not (await client.get_state())["isStreaming"]
    await client.abort()
    with pytest.raises(PiRunOwnershipError, match="fresh client"):
        await client.run("must not be submitted")
    assert client.running  # low-level commands remain usable
    assert (await client.prompt("handled"))["success"]


@pytest.mark.parametrize(
    "limits", [Limits(result_message_count=2), Limits(result_message_bytes=500)]
)
async def test_result_retention_is_bounded_even_with_fast_event_consumer(limits):
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], limits=limits) as pi:
        with pytest.raises(PiResultOverflow):
            async with pi.stream("messages:20") as stream:
                async for _ in stream:
                    pass
                await stream.result()
        assert not pi.busy
        assert (await pi.run("normal")).text == "answer"


@pytest.mark.parametrize("count", [-1, 1.5, True, None])
async def test_invalid_token_counts_are_unknown_without_discarding_other_fields(client, count):
    result = await client.run("usage:" + json.dumps([{"usage": {"input": count}}]))
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens == 3


@pytest.mark.parametrize("cost", [-1, True, None, "invalid", 10**400])
async def test_invalid_cost_is_unknown_without_failing_the_run(client, cost):
    result = await client.run("usage:" + json.dumps([{"usage": {"cost": {"total": cost}}}]))
    assert result.usage.cost is None
    assert result.usage.output_tokens == 3
    assert result.text == "answer"


@pytest.mark.parametrize("reasoning", [0, 4, -1, True, None])
async def test_reasoning_is_unknown_when_ambiguous_or_invalid(client, reasoning):
    result = await client.run(
        "usage:"
        + json.dumps(
            [
                {
                    "usage": {"reasoning": reasoning},
                    "content": [
                        {"type": "thinking", "thinking": "synthetic"},
                        {"type": "text", "text": "one"},
                        {"type": "text", "text": "two"},
                    ],
                }
            ]
        )
    )
    assert result.text == "onetwo"
    assert result.usage.reasoning_tokens is None
    assert result.usage.output_tokens == 3 and result.usage.total_tokens == 6


async def test_missing_measurement_stays_unknown_across_multiple_messages(client):
    result = await client.run(
        "usage:"
        + json.dumps(
            [
                {"usage": None},
                {"usage": {"reasoning": 1}},
            ]
        )
    )
    assert result.usage is not None
    assert result.usage.assistant_messages == 2
    assert result.usage.input_tokens is None and result.usage.reasoning_tokens is None


async def test_bad_text_delta_fails_observers_and_keeps_unknown_events(client):
    async with client.events() as events:
        await client.request("emit", records=[{"type": "future", "value": 1}])
        assert (await anext(events)).raw["value"] == 1
        with pytest.raises(PiProtocolError):
            await client.request(
                "emit",
                records=[
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {"type": "text_delta", "delta": 42},
                    }
                ],
            )
        with pytest.raises(PiProtocolError):
            await anext(events)


@pytest.fixture
async def client():
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)]) as pi:
        yield pi


async def test_readiness_and_early_run_events(client):
    assert client.running and client.compatibility == "tested"
    result = await client.run("normal")
    assert result.text == "answer"
    assert [message["role"] for message in result.messages] == ["user", "assistant"]
    assert result.session.session_id == "current-session"
    assert result.usage.total_tokens == 6  # cumulative delta usage is deliberately 100
    assert result.usage.output_tokens == 3  # reasoning is already included
    assert result.elapsed_seconds >= 0
    assert not client.busy


async def test_empty_run_never_reuses_previous_text(client):
    assert (await client.run("normal")).text == "answer"
    result = await client.run("empty")
    assert result.text == "" and result.messages == []
    assert result.stop_reason is None and result.usage is None


@pytest.mark.parametrize("reason", ["stop", "length", "toolUse", "pending", "deferred"])
async def test_stop_reasons_preserved(client, reason):
    assert (await client.run("stop:" + reason)).stop_reason == reason


@pytest.mark.parametrize("reason", ["error", "aborted"])
async def test_failed_runs_keep_partial_result(client, reason):
    with pytest.raises(PiRunError) as error:
        await client.run("stop:" + reason)
    assert error.value.result.stop_reason == reason
    assert error.value.result.text == "answer"


async def test_recovered_errors_are_events_not_final_failures(client):
    result = await client.run("recovered")
    assert result.stop_reason == "stop"
    assert result.usage.assistant_messages == 2
    assert result.usage.total_tokens == 12


async def test_unknown_usage_stays_unknown(client):
    assert (await client.run("unknown_usage")).usage is None


async def test_stream_events_and_cached_result(client):
    async with client.stream("normal") as stream:
        events = [event async for event in stream]
        assert "".join(event.text_delta or "" for event in events) == "answer"
        result = await stream.result()
        assert await stream.result() is result


async def test_result_cannot_compete_with_iterator(client):
    async with client.stream("normal") as stream:
        async for _event in stream:
            with pytest.raises(PiBusyError):
                await stream.result()
        assert (await stream.result()).text == "answer"


async def test_owned_run_guards_raw_escape_and_keeps_control_commands(client):
    async with client.stream("paused") as stream:
        with pytest.raises(PiBusyError):
            await client.prompt("normal")
        with pytest.raises(PiBusyError):
            await client.request("set_model", provider="test", modelId="test")
        with pytest.raises(PiBusyError):
            await client.run("normal")
        await client.get_state()
        await client.steer("release")
        assert (await stream.result()).text == "answer"


async def test_existing_low_level_work_rejected_by_owned_run(client):
    await client.prompt("paused")
    with pytest.raises(PiBusyError):
        await client.run("normal")
    await client.abort()
    assert not client.busy


async def test_stream_exit_aborts_and_releases_ownership(client):
    async with client.stream("paused"):
        # Entry can precede the prompt response. Establish a response round-trip
        # before testing reusable cleanup of already-acknowledged work.
        await client.get_state()
    assert not client.busy
    assert not (await client.get_state())["isStreaming"]
    assert (await client.run("normal")).text == "answer"


async def test_task_cancellation_before_acceptance_closes_process(client):
    async with client.events() as events:
        task = asyncio.create_task(client.run("preack-paused"))
        while (await anext(events)).type != "agent_start":
            pass
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not client.busy
    assert not client.running


async def test_overall_run_timeout_cleans_up(client):
    with pytest.raises(PiTimeoutError):
        await client.run("paused", timeout=0.1)
    assert not client.busy
    assert not (await client.get_state())["isStreaming"]


async def test_no_start_is_uncertain_and_closes_process():
    pi = AsyncPiClient(
        executable=[sys.executable, str(FAKE)], limits=Limits(run_start_timeout=0.05)
    )
    async with pi:
        with pytest.raises(PiRunStartTimeout) as error:
            await pi.run("handled")
        assert error.value.uncertain
        assert not pi.running and not pi.busy


async def test_rejection_preserves_readiness(client):
    with pytest.raises(PiCommandError):
        await client.run("rejected")
    assert client.running and not client.busy


async def test_future_unknown_events_and_overflow_isolation():
    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)], limits=Limits(event_queue_size=2)
    ) as pi:
        async with pi.events() as events:
            await pi.request("emit", records=[{"type": "future", "novel": True}])
            assert (await anext(events)).raw["novel"]
            await pi.request("emit", records=[{"type": "future"}] * 3)
            with pytest.raises(PiSubscriptionOverflow):
                await anext(events)
        assert (await pi.get_state())["sessionId"] == "current-session"


async def test_owned_stream_overflow_is_explicit_and_cleans_up():
    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)], limits=Limits(event_queue_size=2)
    ) as pi:
        with pytest.raises(PiSubscriptionOverflow):
            await pi.run("flood")
        assert not pi.busy


async def test_null_cycle_and_missing_text(client):
    assert await client.cycle_model() is None
    assert await client.cycle_thinking_level() is None
    assert await client.get_last_assistant_text() is None


async def test_ui_handler_failure_surfaces_without_deadlocking_prompt():
    def broken(request):
        raise ValueError("synthetic UI failure")

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=broken) as pi:
        with pytest.raises(PiUIHandlerError):
            await pi.prompt("ui")
        assert pi.running


@pytest.mark.parametrize("operation", ["prompt", "run", "stream"])
async def test_ui_failure_preserves_original_exception_chain(operation):
    original = ValueError("synthetic callback detail")
    nested = LookupError("synthetic nested cause")

    async def broken(request):
        raise original from nested

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=broken) as pi:
        with pytest.raises(PiUIHandlerError) as caught:
            if operation == "stream":
                async with pi.stream("ui") as stream:
                    await stream.result()
            else:
                await getattr(pi, operation)("ui")
        assert caught.value.__cause__ is original
        assert original.__cause__ is nested
        assert not pi.busy


@pytest.mark.parametrize("operation", ["run", "stream"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_started_ui_failure_preserves_cause_through_cleanup(operation, cleanup_fails):
    original = ValueError("synthetic started callback detail")

    async def broken(request):
        # Round-trip after the prompt ACK so the owner's acceptance wait has
        # completed before this callback fails. No scheduling sleeps needed.
        await pi.get_state()
        raise original

    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)],
        extra_args=["--fail-cleanup"] if cleanup_fails else [],
        ui_handler=broken,
    ) as pi:
        with pytest.raises(PiUIHandlerError) as caught:
            if operation == "stream":
                async with pi.stream("ui-started") as stream:
                    await stream.result()
            else:
                await pi.run("ui-started")
        assert caught.value.__cause__ is original
        assert not pi.busy
        if cleanup_fails:
            assert not pi.running
        else:
            assert pi.running
            assert not (await pi.get_state())["isStreaming"]
            assert (await pi.run("normal")).text == "answer"


async def test_session_argument_conflicts():
    with pytest.raises(ValueError):
        AsyncPiClient(no_session=True, session="saved.jsonl")
    with pytest.raises(ValueError):
        AsyncPiClient(session="saved.jsonl", continue_session=True)


async def test_async_ui_callback_can_close_client_without_cancelling_itself():
    finished = asyncio.Event()

    async def close_from_handler(request):
        await pi.aclose()
        finished.set()

    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)], ui_handler=close_from_handler
    ) as pi:
        with pytest.raises(PiProcessError):
            await pi.prompt("ui")
        async with asyncio.timeout(2):
            await finished.wait()
        assert not pi.running


async def test_slow_ui_callbacks_have_bounded_outstanding_work():
    gate = asyncio.Event()

    async def slow_handler(request):
        await gate.wait()

    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)],
        ui_handler=slow_handler,
        limits=Limits(event_queue_size=2),
    ) as pi:
        with pytest.raises(PiUIHandlerError):
            await pi.request(
                "emit",
                records=[
                    {
                        "type": "extension_ui_request",
                        "id": str(index),
                        "method": "notify",
                        "message": "synthetic",
                    }
                    for index in range(300)
                ],
            )
        assert len(pi._ui_tasks) <= 2
        assert not pi.running


async def test_closed_unentered_stream_never_claims_conversation(client):
    stream = client.stream("normal")
    await stream.aclose()
    with pytest.raises(RuntimeError):
        async with stream:
            pass
    assert not client.busy
    assert (await client.run("normal")).text == "answer"


async def test_preflight_timeout_closes_pi_and_cancels_ui_handler():
    cancelled = asyncio.Event()
    gate = asyncio.Event()

    async def delayed_ui(request):
        try:
            await gate.wait()
            return True
        finally:
            cancelled.set()

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=delayed_ui) as pi:
        with pytest.raises(PiTimeoutError):
            await pi.run("ui", timeout=0.1)
        assert not pi.running and not pi.busy
        assert cancelled.is_set()


async def test_close_during_version_check_waits_for_owned_probe_cleanup(monkeypatch):
    import pi_agent.client as module

    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def gated_version(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(module, "check_version", gated_version)
    pi = AsyncPiClient(executable=sys.executable)
    task = asyncio.create_task(pi.start())
    await entered.wait()
    await pi.aclose()
    assert cleaned.is_set() and task.done() and not pi.running
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_subscription_bytes_bound_independent_of_record_count():
    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)],
        limits=Limits(event_queue_bytes=100),
    ) as pi:
        async with pi.events() as events:
            await pi.request("emit", records=[{"type": "future", "payload": "x" * 200}])
            with pytest.raises(PiSubscriptionOverflow):
                await anext(events)
        assert pi.running


async def test_ui_callback_can_close_during_readiness():
    finished = asyncio.Event()

    async def close_during_startup(request):
        await pi.aclose()
        finished.set()

    pi = AsyncPiClient(
        executable=[sys.executable, str(FAKE)],
        extra_args=["--startup-ui"],
        ui_handler=close_during_startup,
    )
    task = asyncio.create_task(pi.start())
    async with asyncio.timeout(2):
        await finished.wait()
    with pytest.raises(asyncio.CancelledError):
        await task
    await pi.aclose()
    assert not pi.running


async def test_startup_close_does_not_wait_for_callers_enclosing_finally():
    callback_finished = asyncio.Event()

    async def close_from_startup(request):
        await pi.aclose()
        callback_finished.set()

    pi = AsyncPiClient(
        executable=[sys.executable, str(FAKE)],
        extra_args=["--startup-ui"],
        ui_handler=close_from_startup,
    )

    async def application():
        try:
            await pi.start()
        finally:
            await pi.aclose()

    task = asyncio.create_task(application())
    async with asyncio.timeout(2):
        with pytest.raises(asyncio.CancelledError):
            await task
        await callback_finished.wait()
    assert not pi.running
