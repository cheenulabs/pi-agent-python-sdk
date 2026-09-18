"""Already accepted events survive a later terminal process/protocol failure."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import (
    AsyncPiClient,
    Limits,
    PiClient,
    PiProcessError,
    PiProtocolError,
    PiSubscriptionOverflow,
)

FAKE = Path(__file__).with_name("fake_client_pi.py")
RECORDS = [{"type": "future_diagnostic", "index": n, "unknown": {"kept": [n]}} for n in range(3)]


@pytest.mark.parametrize(
    "terminal,error", [("exit", PiProcessError), ("malformed", PiProtocolError)]
)
async def test_async_consumers_drain_independently_before_terminal_error(terminal, error):
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)]) as pi:
        async with pi.events() as first, pi.events() as second:
            await pi.request("emit", records=RECORDS[:1])
            assert (await anext(first)).raw == RECORDS[0]
            with pytest.raises(error) as request_failure:
                await pi.request("emit", records=RECORDS[1:], terminal=terminal)
            await pi.aclose()  # Reaping cannot depend on draining either subscriber.
            for subscriber, records in ((first, RECORDS[1:]), (second, RECORDS)):
                for record in records:
                    assert (await anext(subscriber)).raw == record
                for _ in range(2):
                    with pytest.raises(error) as observed:
                        await anext(subscriber)
                    assert observed.value is request_failure.value
            await second.aclose()
            with pytest.raises(StopAsyncIteration):
                await anext(second)


@pytest.mark.parametrize(
    "terminal,error", [("exit", PiProcessError), ("malformed", PiProtocolError)]
)
def test_blocking_consumers_preserve_order_and_original_terminal_error(terminal, error):
    with PiClient(executable=[sys.executable, str(FAKE)]) as pi:
        with pi.events() as first, pi.events() as second:
            pi.request("emit", records=RECORDS[:1])
            assert next(first).raw == RECORDS[0]
            with pytest.raises(error) as request_failure:
                pi.request("emit", records=RECORDS[1:], terminal=terminal)
            for subscriber, records in ((first, RECORDS[1:]), (second, RECORDS)):
                for record in records:
                    assert next(subscriber).raw == record
                with pytest.raises(error) as observed:
                    next(subscriber)
                assert observed.value is request_failure.value
            first.close()
            with pytest.raises(StopIteration):
                next(first)


async def test_overflow_remains_immediate_and_does_not_stop_a_healthy_consumer():
    async with AsyncPiClient(
        executable=[sys.executable, str(FAKE)], limits=Limits(event_queue_size=1)
    ) as pi:
        async with pi.events() as slow, pi.events() as fast:
            for record in RECORDS:
                await pi.request("emit", records=[record])
                assert (await anext(fast)).raw == record
            with pytest.raises(PiSubscriptionOverflow):
                await anext(slow)
            assert pi.running
            await fast.aclose()
            with pytest.raises(StopAsyncIteration):
                await anext(fast)


async def test_owned_stream_drains_events_then_fails_without_waiting_for_consumer():
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)]) as pi:
        async with pi.stream("paused") as stream:
            assert (await anext(stream)).type == "agent_start"
            with pytest.raises(PiProtocolError):
                # Use an allowed command carrying synthetic fixture controls.
                await pi.request("get_state", emit_before_failure=RECORDS)
            async with asyncio.timeout(5):
                for record in RECORDS:
                    assert (await anext(stream)).raw == record
                with pytest.raises(PiProtocolError):
                    await anext(stream)
        assert not pi.running and not pi.busy
