"""Subscriptions observe the process lifetime, including failed startup."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient, PiProcessError, PiProtocolError

FAKE = Path(__file__).with_name("fake_client_pi.py")


def options(*flags):
    return {"executable": [sys.executable, str(FAKE), *flags]}


async def test_startup_events_are_ordered_independent_and_future_only():
    pi = AsyncPiClient(**options("--startup-events", "--startup-ui"), ui_handler=lambda _: True)
    try:
        async with pi.events() as first, pi.events() as second, pi.events() as removed:
            await removed.aclose()
            await pi.start()
            for sub in (first, second):
                startup = await anext(sub)
                assert startup.raw == {"type": "fixture_startup", "unknown": {"nested": [1, 2]}}
                assert (await anext(sub)).type == "extension_error"
                assert (await anext(sub)).type == "extension_ui_request"
                assert (await anext(sub)).raw["reply"]["confirmed"] is True
            async with pi.events() as later:
                await pi.request("emit", records=[{"type": "later"}])
                assert (await anext(later)).type == "later"
                assert (await anext(first)).type == "later"
            with pytest.raises(StopAsyncIteration):
                await anext(removed)
    finally:
        await pi.aclose()


@pytest.mark.parametrize("blocking", [False, True])
async def test_failed_startup_retains_diagnostics_after_shutdown(blocking):
    def sync():
        pi = PiClient(**options("--startup-events", "--startup-malformed"))
        with pi.events() as events:
            with pytest.raises(PiProtocolError) as failure:
                pi.start()
            assert next(events).type == "fixture_startup"
            assert next(events).type == "extension_error"
            with pytest.raises(PiProtocolError) as terminal:
                next(events)
            assert terminal.value is failure.value
        assert not pi.running
        pi.close()

    if blocking:
        await asyncio.to_thread(sync)
    else:
        pi = AsyncPiClient(**options("--startup-events", "--startup-malformed"))
        async with pi.events() as events:
            with pytest.raises(PiProtocolError) as failure:
                await pi.start()
            assert (await anext(events)).type == "fixture_startup"
            assert (await anext(events)).type == "extension_error"
            with pytest.raises(PiProtocolError) as terminal:
                await anext(events)
            assert terminal.value is failure.value
        await pi.aclose()


def test_sync_prestart_close_never_launches_and_stops_loop():
    pi = PiClient(executable="does-not-exist")
    with pi.events() as events:
        thread = pi._thread
        pi.close()
        assert thread is not None and not thread.is_alive()
        with pytest.raises(PiProcessError):
            next(events)
    with pytest.raises(StopIteration):
        next(events)
    with pytest.raises(PiProcessError):
        pi.start()


def test_sync_prestart_success():
    pi = PiClient(**options("--startup-events"))
    with pi.events() as events:
        try:
            pi.start()
            assert next(events).type == "fixture_startup"
            assert next(events).type == "extension_error"
            with pytest.raises(PiProcessError, match="single-use"):
                pi.start()
        finally:
            pi.close()


async def test_close_before_start_wakes_reader_and_rejects_restart():
    pi = AsyncPiClient(executable="does-not-exist")
    async with pi.events() as events:
        waiter = asyncio.create_task(anext(events))
        await pi.aclose()
        with pytest.raises(PiProcessError):
            await asyncio.wait_for(waiter, 1)
        with pytest.raises(PiProcessError):
            await pi.start()
    await pi.aclose()


async def test_missing_executable_wakes_observer_with_original_failure():
    pi = AsyncPiClient(executable="does-not-exist")
    async with pi.events() as events:
        with pytest.raises(PiProcessError) as failure:
            await pi.start()
        with pytest.raises(PiProcessError) as terminal:
            await anext(events)
        assert terminal.value is failure.value


async def test_cancelling_startup_wakes_consumers():
    reached = asyncio.Event()

    async def handler(_):
        reached.set()
        await asyncio.Event().wait()

    pi = AsyncPiClient(**options("--startup-ui"), ui_handler=handler)
    async with pi.events() as events:
        task = asyncio.create_task(pi.start())
        await asyncio.wait_for(reached.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await anext(events)).type == "extension_ui_request"
        with pytest.raises(PiProcessError):
            await anext(events)
        assert not pi.running


async def test_prestart_registration_binds_loop():
    pi = AsyncPiClient(**options())
    async with pi.events():

        def other_loop():
            with pytest.raises(RuntimeError, match="owning event loop"):
                asyncio.run(pi.start())

        await asyncio.to_thread(other_loop)
        await pi.start()
    await pi.aclose()


async def test_startup_can_drain_while_handshake_waits():
    drained = asyncio.Event()

    async def handler(_):
        await drained.wait()
        return True

    pi = AsyncPiClient(
        **options("--startup-events", "--startup-ui"),
        limits=Limits(event_queue_size=4),
        ui_handler=handler,
    )
    async with pi.events() as events:
        seen = []

        async def drain():
            for _ in range(3):
                seen.append((await anext(events)).type)
            drained.set()

        consumer = asyncio.create_task(drain())
        try:
            await pi.start()
            await asyncio.wait_for(consumer, 2)
            assert seen == ["fixture_startup", "extension_error", "extension_ui_request"]
        finally:
            consumer.cancel()
            await pi.aclose()


@pytest.mark.parametrize("blocking", [False, True])
async def test_version_failure_terminates_prestart_subscription(tmp_path, blocking):
    from pi_agent import PiVersionError

    script = tmp_path / "bad_version.py"
    script.write_text('print("not a Pi version")')
    kwargs = {"executable": [sys.executable, str(script)]}
    if blocking:

        def run():
            pi = PiClient(**kwargs)
            with pi.events() as events:
                with pytest.raises(PiVersionError) as failure:
                    pi.start()
                with pytest.raises(PiVersionError) as terminal:
                    next(events)
                assert terminal.value is failure.value

        await asyncio.to_thread(run)
    else:
        pi = AsyncPiClient(**kwargs)
        async with pi.events() as events:
            with pytest.raises(PiVersionError) as failure:
                await pi.start()
            with pytest.raises(PiVersionError) as terminal:
                await anext(events)
            assert terminal.value is failure.value
