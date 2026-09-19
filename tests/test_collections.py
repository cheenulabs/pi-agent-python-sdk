"""Thin RPC listeners and settlement collection through public client methods."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from pi_agent import (
    AsyncPiClient,
    Limits,
    PiClient,
    PiCommandError,
    PiProcessError,
    PiResultOverflow,
    PiTimeoutError,
)

FAKE = [sys.executable, str(Path(__file__).with_name("fake_client_pi.py"))]


@pytest.mark.parametrize("count", [100, 1000, 5000])
@pytest.mark.parametrize("ack", ["first", "last"])
async def test_async_prompt_collection_preserves_bursts(count, ack):
    async with AsyncPiClient(executable=FAKE) as client:
        events = await client.prompt_and_wait(f"burst:{count}:{ack}", timeout=10)
        assert [event.raw["sequence"] for event in events if event.text_delta] == list(range(count))
        assert events[-1].type == "agent_settled"
        assert len(events) == count + 3
        assert (await client.prompt_and_wait("normal"))[-1].type == "agent_settled"
        assert not client.busy


@pytest.mark.parametrize("count", [100, 1000, 5000])
@pytest.mark.parametrize("ack", ["first", "last"])
def test_sync_prompt_collection_preserves_bursts(count, ack):
    with PiClient(executable=FAKE) as client:
        events = client.prompt_and_wait(f"burst:{count}:{ack}", timeout=10)
        assert [event.raw["sequence"] for event in events if event.text_delta] == list(range(count))
        assert len(events) == count + 3
        assert client.prompt_and_wait("normal")[-1].type == "agent_settled"
        assert not client.busy


async def test_collection_is_registered_before_awaiting_and_can_start_before_pi():
    client = AsyncPiClient(executable=[*FAKE, "--startup-events"])
    pending = client.collect_events()
    try:
        await client.start()
        await client.prompt("normal")
        events = await pending
        assert events[0].type == "fixture_startup"
        assert events[-1].type == "agent_settled"
    finally:
        await client.aclose()


async def test_wait_for_idle_waits_for_next_settlement_without_retaining_history():
    async with AsyncPiClient(executable=FAKE, limits=Limits(collection_event_count=1)) as client:
        pending = client.wait_for_idle()
        await client.get_state()
        assert not pending.done()
        await client.prompt("burst:5000:last")
        assert await pending is None


@pytest.mark.parametrize(
    "limits", [Limits(collection_event_count=3), Limits(collection_event_bytes=100)]
)
async def test_collection_history_is_bounded_independently_of_consumption(limits):
    async with AsyncPiClient(executable=FAKE, limits=limits) as client:
        with pytest.raises(PiResultOverflow):
            await client.prompt_and_wait("burst:1000:first")
        assert client.running
        assert not (await client.get_state())["isStreaming"]


async def test_late_acknowledgement_is_required_even_after_settlement():
    async with AsyncPiClient(executable=FAKE) as client, client.events() as events:
        pending = asyncio.create_task(client.prompt_and_wait("preack-settled"))
        while (await anext(events)).type != "agent_settled":
            pass
        assert not pending.done()
        await client.steer("reject")
        with pytest.raises(PiCommandError):
            await pending
        assert client.running


@pytest.mark.parametrize("operation", ["collect_events", "wait_for_idle"])
async def test_collector_timeout_does_not_abort_pi(operation):
    async with AsyncPiClient(executable=FAKE) as client:
        await client.prompt("paused")
        with pytest.raises(PiTimeoutError):
            await getattr(client, operation)(timeout=0.02)
        assert (await client.get_state())["isStreaming"]
        await client.abort()


async def test_prompt_collection_timeout_and_cancel_leave_explicit_control_to_caller():
    async with AsyncPiClient(executable=FAKE) as client, client.events() as events:
        pending = asyncio.create_task(client.prompt_and_wait("paused"))
        assert (await anext(events)).type == "agent_start"
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert (await client.get_state())["isStreaming"]
        await client.abort()
        with pytest.raises(PiTimeoutError) as caught:
            await client.prompt_and_wait("handled", timeout=0.02)
        assert caught.value.uncertain
        assert client.running


@pytest.mark.parametrize("operation", ["collect_events", "wait_for_idle"])
async def test_prestart_close_wakes_collectors(operation):
    client = AsyncPiClient(executable=FAKE)
    pending = getattr(client, operation)()
    await client.aclose()
    with pytest.raises(PiProcessError):
        await pending


async def test_listener_order_unsubscribe_and_exception_isolation():
    client = AsyncPiClient(executable=[*FAKE, "--startup-events"])
    observed = []
    errors = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: errors.append(context))
    original = ValueError("synthetic listener failure")

    def broken(event):
        raise original

    remove_broken = client.on_event(broken)
    remove = client.on_event(lambda event: observed.append(event.raw))
    try:
        await client.start()
        assert observed[0]["type"] == "fixture_startup"
        assert errors[0]["exception"] is original
        remove_broken()
        remove_broken()
        remove()
        count = len(observed)
        await client.prompt_and_wait("normal")
        assert len(observed) == count
    finally:
        await client.aclose()
        loop.set_exception_handler(previous)


async def test_unsubscribe_during_dispatch_skips_removed_and_defers_added_listeners():
    async with AsyncPiClient(executable=FAKE) as client:
        seen = []
        removals = []

        def first(event):
            seen.append(("first", event.raw["index"]))
            remove_second()
            remove_first()
            removals.append(client.on_event(lambda e: seen.append(("third", e.raw["index"]))))

        remove_first = client.on_event(first)
        remove_second = client.on_event(lambda e: seen.append(("second", e.raw["index"])))
        await client.request("emit", records=[{"type": "future", "index": i} for i in range(2)])
        assert seen == [("first", 0), ("third", 1)]
        for remove in removals:
            remove()


def test_sync_listener_registration_thread_and_self_unsubscribe():
    client = PiClient(executable=[*FAKE, "--startup-events"])
    seen = []

    def listener(event):
        seen.append((event.type, threading.get_ident()))
        with pytest.raises(RuntimeError, match="callbacks"):
            client.get_state()
        remove()

    remove = client.on_event(listener)
    try:
        client.start()
        assert len(seen) == 1 and seen[0][0] == "fixture_startup"
        assert seen[0][1] != threading.get_ident()
        client.prompt_and_wait("normal")
        assert len(seen) == 1
    finally:
        client.close()
    remove()
    remove()


async def test_async_listener_is_rejected():
    client = AsyncPiClient(executable=FAKE)

    async def listener(event):
        pass

    with pytest.raises(TypeError, match="synchronous"):
        client.on_event(listener)
    await client.aclose()


async def test_listener_mutation_does_not_change_other_listeners_or_collections():
    async with AsyncPiClient(executable=FAKE) as client:
        seen = []
        client.on_event(lambda event: event.raw.clear())
        client.on_event(lambda event: seen.append(event.raw))
        pending = client.collect_events()
        records = [{"type": "future", "unknown": {"nested": [1, 2]}}, {"type": "agent_settled"}]
        await client.request("emit", records=records)
        assert [event.raw for event in await pending] == records == seen


@pytest.mark.parametrize("operation", ["collect_events", "wait_for_idle"])
@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan")])
async def test_invalid_collection_deadline(operation, timeout):
    async with AsyncPiClient(executable=FAKE) as client:
        with pytest.raises(ValueError):
            getattr(client, operation)(timeout=timeout)


async def test_cancel_before_collection_starts_and_independent_collectors():
    async with AsyncPiClient(executable=FAKE) as client:
        cancelled = client.collect_events()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        first, second = client.collect_events(timeout=None), client.collect_events()
        await client.prompt("normal")
        assert [e.raw for e in await first] == [e.raw for e in await second]
        assert (await client.prompt_and_wait("normal"))[-1].type == "agent_settled"


@pytest.mark.parametrize("terminal", ["exit", "malformed"])
async def test_terminal_failure_wakes_collection(terminal):
    from pi_agent import PiProtocolError

    async with AsyncPiClient(executable=FAKE) as client:
        pending = client.collect_events()
        with pytest.raises((PiProcessError, PiProtocolError)):
            await client.request("emit", records=[{"type": "future"}], terminal=terminal)
        with pytest.raises((PiProcessError, PiProtocolError)):
            await pending


async def test_model_failure_remains_an_event_and_command_rejection_is_an_error():
    async with AsyncPiClient(executable=FAKE) as client:
        events = await client.prompt_and_wait("stop:error")
        assert any(e.raw.get("message", {}).get("stopReason") == "error" for e in events)
        with pytest.raises(PiCommandError):
            await client.prompt_and_wait("rejected")
        assert (await client.prompt_and_wait("normal"))[-1].type == "agent_settled"


async def test_prompt_collection_preserves_ui_failure_cause():
    from pi_agent import PiUIHandlerError

    original = ValueError("synthetic UI failure")

    def handler(request):
        raise original

    async with AsyncPiClient(executable=FAKE, ui_handler=handler) as client:
        with pytest.raises(PiUIHandlerError) as caught:
            await client.prompt_and_wait("ui")
        assert caught.value.__cause__ is original
        assert client.running
        assert (await client.prompt_and_wait("normal"))[-1].type == "agent_settled"


@pytest.mark.parametrize("operation", ["collect_events", "wait_for_idle"])
def test_blocking_collection_timeout_and_close(operation):
    from concurrent.futures import ThreadPoolExecutor

    with PiClient(executable=FAKE) as client:
        with pytest.raises(PiTimeoutError) as caught:
            getattr(client, operation)(timeout=0.02)
        assert not caught.value.uncertain
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(getattr(client, operation), timeout=None)
            client.close()
            with pytest.raises(PiProcessError):
                pending.result(timeout=5)


@pytest.mark.parametrize("operation", ["collect_events", "wait_for_idle"])
def test_blocking_collection_observes_next_settlement(operation, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    registered = threading.Event()
    original = getattr(AsyncPiClient, operation)

    def register(client, **kwargs):
        task = original(client, **kwargs)
        registered.set()
        return task

    monkeypatch.setattr(AsyncPiClient, operation, register)
    client = PiClient(executable=FAKE)
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(getattr(client, operation), timeout=5)
        assert registered.wait(timeout=5)
        client.start()
        try:
            client.prompt("normal")
            result = pending.result(timeout=5)
            if operation == "collect_events":
                assert result[-1].type == "agent_settled"
            else:
                assert result is None
        finally:
            client.close()


async def test_escaped_unicode_survives_listeners_and_collection():
    async with AsyncPiClient(executable=FAKE) as client:
        seen = []
        client.on_event(seen.append)
        pending = client.collect_events()
        try:
            await client.request("emit_escaped")
            events = await pending
            assert events[0].raw["value"] == chr(0xD800)
            assert [e.raw for e in events] == [e.raw for e in seen]
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_concurrent_collectors_and_idle_waiter_share_one_settlement():
    async with AsyncPiClient(executable=FAKE) as pi:
        first, second, idle = pi.collect_events(), pi.collect_events(), pi.wait_for_idle()
        await pi.prompt("normal")
        one, two, settled = await asyncio.gather(first, second, idle)
        assert [e.raw for e in one] == [e.raw for e in two]
        assert one[-1].type == "agent_settled" and settled is None


async def test_prompt_overall_deadline_includes_ack_after_settlement():
    async with AsyncPiClient(executable=FAKE) as pi, pi.events() as events:
        pending = asyncio.create_task(pi.prompt_and_wait("preack-settled", timeout=0.5))
        while (await anext(events)).type != "agent_settled":
            pass
        with pytest.raises(PiTimeoutError) as caught:
            await pending
        assert caught.value.command == "prompt" and caught.value.uncertain
        assert pi.running
        # Release the late response explicitly; no automatic abort/close occurred.
        await pi.steer("ack")
        assert (await pi.prompt_and_wait("normal"))[-1].type == "agent_settled"
