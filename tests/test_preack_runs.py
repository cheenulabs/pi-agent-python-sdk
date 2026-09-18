"""Run events can precede the authoritative prompt response."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, PiClient, PiCommandError, PiProcessError, PiTimeoutError

FAKE = Path(__file__).with_name("fake_client_pi.py")


@pytest.mark.parametrize("reject", [False, True])
async def test_settlement_before_ack_does_not_complete_the_result(reject):
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)]) as pi:
        async with asyncio.timeout(5):
            async with pi.stream("preack-settled") as stream:
                assert (await anext(stream)).type == "agent_start"
                assert (await anext(stream)).raw["message"]["content"][0]["text"] == "answer"
                assert (await anext(stream)).type == "agent_settled"

                async def finish():
                    with pytest.raises(StopAsyncIteration):
                        await anext(stream)
                    return await stream.result()

                result = asyncio.create_task(finish())
                try:
                    await pi.get_state()  # Barrier after starting the result waiter.
                    assert not result.done()
                    await pi.steer("reject" if reject else "ack")
                    if reject:
                        with pytest.raises(PiCommandError, match="prompt"):
                            await result
                    else:
                        assert (await result).text == "answer"
                finally:
                    if not result.done():
                        result.cancel()
                    await asyncio.gather(result, return_exceptions=True)
        assert not pi.busy
        assert pi.running is not reject


@pytest.mark.parametrize(
    "ending", ["exit", "cancel", "deadline", "run-deadline", "close", "process-exit", "reject"]
)
async def test_unacknowledged_started_run_is_cleaned_up(ending):
    async with AsyncPiClient(executable=[sys.executable, str(FAKE)]) as pi:
        async with asyncio.timeout(5):
            async with pi.stream(
                "preack-paused",
                command_timeout=0.1 if ending == "deadline" else None,
                timeout=0.1 if ending == "run-deadline" else None,
            ) as stream:
                if ending == "exit":
                    pass  # Early context exit before acknowledgement must close Pi.
                elif ending == "cancel":
                    task = asyncio.create_task(stream.result())
                    await pi.get_state()
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                elif ending in {"deadline", "run-deadline"}:
                    with pytest.raises(PiTimeoutError):
                        await stream.result()
                elif ending == "close":
                    await pi.aclose()
                    with pytest.raises(PiProcessError):
                        await stream.result()
                elif ending == "process-exit":
                    with pytest.raises(PiProcessError):
                        await pi.steer("exit")
                    with pytest.raises(PiProcessError):
                        await stream.result()
                else:
                    await pi.steer("reject")
                    with pytest.raises(PiCommandError):
                        await stream.result()
        assert not pi.running and not pi.busy


@pytest.mark.parametrize("ending", ["exit", "reject", "deadline"])
def test_sync_unacknowledged_stream_cleanup(ending):
    with PiClient(executable=[sys.executable, str(FAKE)]) as pi:
        with pi.stream(
            "preack-paused", command_timeout=0.1 if ending == "deadline" else None
        ) as stream:
            if ending == "reject":
                pi.steer("reject")
                with pytest.raises(PiCommandError):
                    list(stream)
            elif ending == "deadline":
                with pytest.raises(PiTimeoutError):
                    list(stream)
        assert not pi.running and not pi.busy


def test_sync_unacknowledged_run_times_out_and_closes():
    with PiClient(executable=[sys.executable, str(FAKE)]) as pi:
        with pytest.raises(PiTimeoutError):
            pi.run("preack-paused", command_timeout=0.1)
        assert not pi.running and not pi.busy
