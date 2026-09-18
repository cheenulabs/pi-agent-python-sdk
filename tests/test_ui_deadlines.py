"""Distinguish protocol dialog expiry from callback and caller failures."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, PiUIHandlerError

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
