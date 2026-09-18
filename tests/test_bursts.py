"""Finite unpaced output must not starve an immediately consuming caller."""

import asyncio
import concurrent.futures
import sys
import threading
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, PiBusyError, PiClient, PiProtocolError, PiSubscriptionOverflow
from pi_agent.types import Limits

FAKE = [sys.executable, str(Path(__file__).with_name("fake_client_pi.py"))]


@pytest.mark.parametrize("count", [100, 1000, 5000])
@pytest.mark.parametrize("acknowledgement", ["first", "last"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_async_finite_burst(count, acknowledgement, streaming):
    async with AsyncPiClient(executable=FAKE) as client:
        prompt = f"burst:{count}:{acknowledgement}"
        if streaming:
            seen = []
            async with client.stream(prompt, timeout=10) as stream:
                async for event in stream:
                    if event.text_delta:
                        seen.append(event.raw["sequence"])
                result = await stream.result()
            assert seen == list(range(count))
        else:
            result = await client.run(prompt, timeout=10)
        assert result.text == "x" * count
        assert (await client.run("normal")).text == "answer"


@pytest.mark.parametrize("count", [100, 1000, 5000])
@pytest.mark.parametrize("acknowledgement", ["first", "last"])
@pytest.mark.parametrize("streaming", [False, True])
def test_sync_finite_burst(count, acknowledgement, streaming):
    with PiClient(executable=FAKE) as client:
        prompt = f"burst:{count}:{acknowledgement}"
        if streaming:
            seen = []
            with client.stream(prompt, timeout=10) as stream:
                for event in stream:
                    if event.text_delta:
                        seen.append(event.raw["sequence"])
                result = stream.result()
            assert seen == list(range(count))
        else:
            result = client.run(prompt, timeout=10)
        assert result.text == "x" * count
        assert client.run("normal").text == "answer"


async def test_result_only_run_does_not_retain_progress():
    async with AsyncPiClient(
        executable=FAKE, limits=Limits(event_queue_size=1, event_queue_bytes=1)
    ) as client:
        assert (await client.run("burst:5000:last", timeout=10)).text == "x" * 5000


@pytest.mark.parametrize("observation", [False, True])
async def test_async_subscription_consumes_finite_burst(observation):
    async with AsyncPiClient(executable=FAKE) as client:
        subscription = client.observe(stderr=False, rpc=True) if observation else client.events()
        async with subscription as events:

            async def consume():
                seen = []
                async for event in events:
                    raw = event.data if observation else event.raw
                    if raw["type"] == "message_update":
                        seen.append(raw["sequence"])
                    if raw["type"] == "agent_settled":
                        return seen

            task = asyncio.create_task(consume())
            await client.prompt("burst:5000:last")
            assert await asyncio.wait_for(task, 10) == list(range(5000))


@pytest.mark.parametrize("observation", [False, True])
def test_sync_subscription_consumes_finite_burst(observation):
    with PiClient(executable=FAKE) as client:
        subscription = client.observe(stderr=False, rpc=True) if observation else client.events()
        with subscription as events, concurrent.futures.ThreadPoolExecutor() as executor:
            ready = threading.Event()

            def consume():
                seen = []
                ready.set()
                for event in events:
                    raw = event.data if observation else event.raw
                    if raw["type"] == "message_update":
                        seen.append(raw["sequence"])
                    if raw["type"] == "agent_settled":
                        return seen

            pending = executor.submit(consume)
            assert ready.wait(5)
            client.prompt("burst:5000:last")
            assert pending.result(10) == list(range(5000))


def test_sync_partial_batch_preserves_run_consumption_rules():
    with PiClient(executable=FAKE) as client:
        with client.stream("burst:100:first") as stream:
            # Let the finite run settle before consuming its buffered events.
            client.get_state()
            assert next(stream).type == "agent_start"
            with pytest.raises(PiBusyError, match="Finish iteration"):
                stream.result()
            remaining = list(stream)
            assert len(remaining) == 102
            assert stream.result().text == "x" * 100
        with pytest.raises(StopIteration):
            next(stream)


@pytest.mark.parametrize("observation", [False, True])
def test_sync_overflow_discards_prefetched_events(observation):
    with PiClient(executable=FAKE) as client:
        subscription = client.observe(stderr=False, rpc=True) if observation else client.events()
        with subscription as events:
            client.request("emit", records=[{"type": "future"}] * 100)
            next(events)
            client.request("emit", records=[{"type": "future"}] * 1000)
            with pytest.raises(PiSubscriptionOverflow):
                next(events)
        assert not client.get_state()["isStreaming"]


def test_closing_sync_observation_reports_unconsumed_batch():
    with PiClient(executable=FAKE) as client:
        with client.observe(stderr=False, rpc=True) as output:
            client.request("emit", records=[{"type": "future"}] * 20)
            next(output)
        assert output.status.lost
        with pytest.raises(StopIteration):
            next(output)


def test_sync_buffered_failure_preserves_prefix_across_batches_and_close():
    with PiClient(executable=FAKE) as client, client.events() as events:
        records = [{"type": "future", "sequence": i} for i in range(180)]
        with pytest.raises(PiProtocolError):
            client.request("get_state", emit_before_failure=records)
        assert next(events).raw["sequence"] == 0
        client.close()
        assert [next(events).raw["sequence"] for _ in range(179)] == list(range(1, 180))
        with pytest.raises(PiProtocolError):
            next(events)


def test_sync_run_does_not_retain_progress():
    with PiClient(
        executable=FAKE, limits=Limits(event_queue_size=1, event_queue_bytes=1)
    ) as client:
        assert client.run("burst:5000:last", timeout=10).text == "x" * 5000


def test_sync_overflowed_stream_discards_batch_and_closes_cleanly():
    with PiClient(executable=FAKE) as client:
        with client.stream("paused") as stream:
            # Prefetch a bounded batch, then stop consuming while more events arrive.
            client.request("get_state", emit=[{"type": "future"}] * 100)
            assert next(stream).type == "agent_start"
            client.request("get_state", emit=[{"type": "future"}] * 1000)
            with pytest.raises(PiSubscriptionOverflow):
                next(stream)
        with pytest.raises(StopIteration):
            next(stream)
        assert not client.busy
        assert client.run("normal").text == "answer"
