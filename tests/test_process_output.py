"""Caller-owned byte reconstruction across startup, commands and bounded cleanup."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient, PiSubscriptionOverflow

FAKE = Path(__file__).with_name("fake_output_pi.py")
START = b"startup\xff\xe2"
NORMAL = b"\x82\xac" + b"diagnostic" * 1000
END = b"shutdown\x00\xfe"


def options(**kwargs):
    return {"executable": [sys.executable, str(FAKE)], **kwargs}


async def test_async_output_survives_close_and_is_independent_of_tail():
    pi = AsyncPiClient(**options(limits=Limits(stderr_tail_bytes=4)))
    async with pi.observe() as observation:
        try:
            await pi.start()
            await pi.request("diagnostic")
        finally:
            await pi.aclose()
        records = [record async for record in observation]
        assert b"".join(r.data for r in records) == START + NORMAL + END
        assert all(r.source == "stderr" and r.time_ns > 0 for r in records)
        assert observation.status.complete
        assert observation.status.stderr_eof
        assert observation.status.from_start
        assert observation.status.ended_at_ns >= observation.status.started_at_ns
        assert pi.stderr_tail == END[-4:].decode(errors="replace")
        assert "startup" not in repr(records)
        assert "Pi client closed" not in repr(observation.status)


def test_sync_collect_and_forward_original_bytes_after_close():
    import io

    pi = PiClient(**options())
    with pi.observe() as observation:
        try:
            pi.start()
            pi.request("diagnostic")
        finally:
            pi.close()
        destination = io.BytesIO()
        collected = bytearray()
        for record in observation:
            destination.write(record.data)
            collected.extend(record.data)
        assert destination.getvalue() == bytes(collected) == START + NORMAL + END
        assert observation.status.complete
        assert pi.stderr_tail == ""


async def test_overflow_is_local_and_explicit():
    pi = AsyncPiClient(**options(limits=Limits(event_queue_bytes=100)))
    async with pi.observe() as slow:
        try:
            await pi.start()
            await pi.request("diagnostic")
            await pi.aclose()
            with pytest.raises(PiSubscriptionOverflow):
                async for _ in slow:
                    pass
            assert slow.status.lost and not slow.status.complete
        finally:
            await pi.aclose()


async def test_failed_consumer_does_not_break_commands_or_other_observers():
    pi = AsyncPiClient(**options())
    async with pi.observe() as good:
        try:
            with pytest.raises(ValueError):
                async with pi.observe() as bad:
                    await pi.start()
                    await anext(bad)
                    raise ValueError("caller-owned sink failed")
            assert not bad.status.complete
            await pi.request("diagnostic")
        finally:
            await pi.aclose()
        assert b"".join([r.data async for r in good]) == START + NORMAL + END
        assert good.status.complete


async def test_inherited_pipe_is_incomplete_and_bounded():
    pi = AsyncPiClient(**options(limits=Limits(cleanup_timeout=0.03)))
    async with pi.observe() as observation:
        await pi.start()
        await pi.request("inherit")
        await asyncio.wait_for(pi.aclose(), 1)
        records = [r async for r in observation]
        assert b"".join(r.data for r in records) == START + END
        assert not observation.status.complete
        assert not observation.status.stderr_eof


async def test_late_and_explicitly_closed_observers_are_not_complete():
    pi = AsyncPiClient(**options())
    await pi.start()
    async with pi.observe() as late:
        await pi.aclose()
        async for _ in late:
            pass
        assert not late.status.complete
        assert not late.status.from_start
