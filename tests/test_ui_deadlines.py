"""Distinguish protocol dialog expiry from callback and caller failures."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, PiClient, PiUIHandlerError

FAKE = Path(__file__).with_name("fake_client_pi.py")


def dialog(request_id, timeout=25):
    return {
        "type": "extension_ui_request",
        "id": request_id,
        "method": "confirm",
        "title": "Synthetic deadline",
        "message": "Continue?",
        "timeout": timeout,
    }


@pytest.mark.parametrize("timeout", [0, -1])
async def test_no_deadline_allows_async_handler_to_await(timeout):
    async def handler(request):
        await asyncio.sleep(0)
        return True

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=handler) as pi:
        async with pi.events() as events, asyncio.timeout(5):
            await pi.request("emit", records=[dialog("no-deadline", timeout)])
            assert (await anext(events)).raw["id"] == "no-deadline"
            assert (await anext(events)).raw["reply"] == {
                "type": "extension_ui_response",
                "id": "no-deadline",
                "confirmed": True,
            }
            assert (await pi.get_state())["sessionId"]


def test_zero_deadline_allows_blocking_handler_to_return():
    release = threading.Event()

    def handler(request):
        assert release.wait(5)
        return "synthetic answer"

    request = {**dialog("zero", 0), "method": "input"}
    with PiClient(executable=[sys.executable, str(FAKE)], ui_handler=handler) as pi:
        with pi.events() as events:
            try:
                pi.request("emit", records=[request])
                assert next(events).raw["id"] == "zero"
            finally:
                release.set()
            assert next(events).raw["reply"] == {
                "type": "extension_ui_response",
                "id": "zero",
                "value": "synthetic answer",
            }
            assert pi.get_state()["sessionId"]


@pytest.mark.parametrize("suppress_cancellation", [False, True])
async def test_expired_answer_is_cancelled_and_next_dialog_still_works(suppress_cancellation):
    async def handler(request):
        if request["id"] == "expired":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if suppress_cancellation:
                    return True
                raise
        return False

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=handler) as pi:
        async with pi.events() as events, asyncio.timeout(5):
            await pi.request("emit", records=[dialog("expired")])
            assert (await anext(events)).type == "extension_ui_request"
            assert (await anext(events)).raw["reply"] == {
                "type": "extension_ui_response",
                "id": "expired",
                "cancelled": True,
            }
            await pi.request("emit", records=[dialog("next", 5000)])
            assert (await anext(events)).raw["id"] == "next"
            assert (await anext(events)).raw["reply"] == {
                "type": "extension_ui_response",
                "id": "next",
                "confirmed": False,
            }
            assert (await pi.get_state())["sessionId"]


@pytest.mark.parametrize("error_type", [TimeoutError, ValueError])
async def test_callback_exception_before_deadline_remains_an_error(error_type):
    original = error_type("synthetic independent failure")

    async def handler(request):
        raise original

    async with AsyncPiClient(executable=[sys.executable, str(FAKE)], ui_handler=handler) as pi:
        async with pi.events() as events, asyncio.timeout(5):
            with pytest.raises(PiUIHandlerError) as caught:
                await pi.request("emit", records=[dialog("failure", 5000)])
                async for _ in events:
                    pass
            assert caught.value.__cause__ is original
