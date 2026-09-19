"""JSON string fidelity through actual subprocess commands and UI replies."""

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient

FAKE = [sys.executable, str(Path(__file__).with_name("fake_pi.py"))]
STRINGS = ["\ud800", "\udfff", "before\ud800after", "😀", "é\u2028\u2029", '\0\n\r\t\\"']


@pytest.mark.parametrize("value", STRINGS)
async def test_async_outbound_strings_round_trip(value):
    async with AsyncPiClient(executable=FAKE) as pi:
        assert (await pi.request("echo", data={"value": value}))["data"] == {"value": value}


@pytest.mark.parametrize("value", STRINGS)
def test_blocking_outbound_strings_round_trip(value):
    with PiClient(executable=FAKE) as pi:
        assert pi.request("echo", data={"value": value})["data"] == {"value": value}


@pytest.mark.parametrize("method", ["input", "editor"])
async def test_ui_string_reply_preserves_value_and_id(method):
    value = "before\ud800after"
    async with AsyncPiClient(executable=FAKE, ui_handler=lambda _: value) as pi:
        async with pi.events() as events:
            await pi.request("ui_input", method=method)
            async with asyncio.timeout(5):
                async for event in events:
                    if event.type == "ui_received":
                        assert event.raw["reply"] == {
                            "type": "extension_ui_response",
                            "id": "string-dialog",
                            "value": value,
                        }
                        break
            assert (await pi.get_state())["sessionId"] == "fake-session"


@pytest.mark.parametrize("extra", [0, 1])
async def test_outbound_byte_limit_counts_json_escapes_before_writing(extra):
    # Startup uses ID 1; the first application request uses ID 2.
    expected = b'{"type":"record_size","id":"2","value":"' + b"\\ud800" * 100 + b'"}'
    async with AsyncPiClient(executable=FAKE, limits=Limits(max_record_bytes=len(expected))) as pi:
        if extra:
            with pytest.raises(ValueError, match="max_record_bytes"):
                await pi.request("record_size", value="\ud800" * 101)
            # Rejection was local and did not invalidate framing/the child.
            assert (await pi.request("echo", data="still usable"))["data"] == "still usable"
        else:
            response = await pi.request("record_size", value="\ud800" * 100)
            assert response["data"]["bytes"] == len(expected)
