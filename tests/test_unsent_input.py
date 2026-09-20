"""Locally rejected input must not claim or close a healthy conversation."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient, PiRunOwnershipError

FAKE = [sys.executable, str(Path(__file__).with_name("fake_client_pi.py"))]
METHODS = ["prompt", "steer", "follow_up", "request", "run", "stream"]


def invalid_input(failure):
    if failure == "size":
        return {"message": "x" * 2001}, ValueError
    return {"message": "normal", "images": [object()]}, TypeError


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("failure", ["size", "json"])
async def test_async_rejected_input_keeps_client_usable(method, failure):
    fields, error = invalid_input(failure)
    async with AsyncPiClient(executable=FAKE, limits=Limits(max_record_bytes=2000)) as pi:
        observed = []
        unsubscribe = pi.on_event(observed.append)
        with pytest.raises(error):
            if method == "stream":
                async with pi.stream(**fields) as stream:
                    await stream.result()
            elif method == "request":
                await pi.request("prompt", **fields)
            else:
                await getattr(pi, method)(**fields)
        assert pi.running and not pi.busy
        assert not (await pi.get_state())["isStreaming"]
        assert observed == []
        unsubscribe()
        assert (await pi.run("normal")).text == "answer"


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("failure", ["size", "json"])
def test_blocking_rejected_input_keeps_client_usable(method, failure):
    fields, error = invalid_input(failure)
    with PiClient(executable=FAKE, limits=Limits(max_record_bytes=2000)) as pi:
        observed = []
        unsubscribe = pi.on_event(observed.append)
        with pytest.raises(error):
            if method == "stream":
                with pi.stream(**fields) as stream:
                    stream.result()
            elif method == "request":
                pi.request("prompt", **fields)
            else:
                getattr(pi, method)(**fields)
        assert pi.running and not pi.busy
        assert not pi.get_state()["isStreaming"]
        assert observed == []
        unsubscribe()
        assert pi.run("normal").text == "answer"


@pytest.mark.parametrize("concurrent", [False, True])
async def test_rejection_does_not_undo_a_real_unowned_submission(concurrent):
    async with AsyncPiClient(executable=FAKE, limits=Limits(max_record_bytes=2000)) as pi:
        if concurrent:
            results = await asyncio.gather(
                pi.prompt("x" * 2001), pi.prompt("handled"), return_exceptions=True
            )
            assert isinstance(results[0], ValueError) and results[1] is None
        else:
            await pi.prompt("handled")
            with pytest.raises(ValueError):
                await pi.prompt("x" * 2001)
        with pytest.raises(PiRunOwnershipError):
            await pi.run("normal")
        assert pi.running


async def test_reserved_raw_fields_do_not_claim_submission():
    async with AsyncPiClient(executable=FAKE) as pi:
        with pytest.raises(ValueError, match="override"):
            await pi.request("prompt", message="normal", id="caller-id")
        assert (await pi.run("normal")).text == "answer"
