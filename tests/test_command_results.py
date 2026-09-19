"""TS-shaped command results and no hidden session refresh requests."""

import sys
from pathlib import Path

import pytest

from pi_agent import AsyncPiClient, PiClient, PiCommandError

FAKE = [sys.executable, str(Path(__file__).with_name("fake_contract_pi.py"))]
MUTATIONS = [
    ("new_session", (), {"parent_session": "parent"}, {"parentSession": "parent"}),
    ("switch_session", ("saved",), {}, {"sessionPath": "saved"}),
    ("fork", ("entry",), {}, {"entryId": "entry"}),
    ("clone", (), {}, {}),
    ("set_session_name", ("name",), {}, {"name": "name"}),
]


async def test_async_command_results_and_checked_prompt():
    async with AsyncPiClient(executable=FAKE) as pi:
        assert await pi.cycle_thinking_level() == {
            "level": "high",
            "futureMetadata": {"kept": [1, 2]},
        }
        assert await pi.export_html() == {
            "path": "/synthetic/export.html",
            "futureMetadata": {"kept": [1, 2]},
        }
        assert await pi.prompt("handled") is None
        receipt = await pi.request("prompt", message="handled")
        assert receipt["success"] and receipt["id"] and receipt["command"] == "prompt"
        with pytest.raises(PiCommandError):
            await pi.prompt("reject")
        await pi.request("configure", nullable=True)
        assert await pi.cycle_thinking_level() is None


def test_blocking_command_results_and_checked_prompt():
    with PiClient(executable=FAKE) as pi:
        assert pi.cycle_thinking_level() == {"level": "high", "futureMetadata": {"kept": [1, 2]}}
        assert pi.export_html() == {
            "path": "/synthetic/export.html",
            "futureMetadata": {"kept": [1, 2]},
        }
        assert pi.prompt("handled") is None
        assert pi.request("prompt", message="handled")["success"]
        with pytest.raises(PiCommandError):
            pi.prompt("reject")
        pi.request("configure", nullable=True)
        assert pi.cycle_thinking_level() is None


@pytest.mark.parametrize("method,args,kwargs,wire", MUTATIONS)
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_async_mutation_sends_only_requested_command(
    method, args, kwargs, wire, raw, cancelled
):
    async with AsyncPiClient(executable=FAKE) as pi:
        await pi.request("configure", reject_state=True, cancelled=cancelled)
        if raw:
            result = (await pi.request(method, timeout=1, **wire))["data"]
        else:
            result = await getattr(pi, method)(*args, timeout=1, **kwargs)
        if method != "set_session_name":
            assert result == {"cancelled": cancelled}
        received = (await pi.request("received"))["data"]["requests"]
        assert received == [{"type": method, **wire}]
        assert pi.session.session_id is None
        await pi.request("configure")
        assert (await pi.get_state())["sessionId"] == pi.session.session_id == "fixture"


@pytest.mark.parametrize("method,args,kwargs,wire", MUTATIONS)
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_blocking_mutation_sends_only_requested_command(method, args, kwargs, wire, raw, cancelled):
    with PiClient(executable=FAKE) as pi:
        pi.request("configure", reject_state=True, cancelled=cancelled)
        if raw:
            result = pi.request(method, timeout=1, **wire)["data"]
        else:
            result = getattr(pi, method)(*args, timeout=1, **kwargs)
        if method != "set_session_name":
            assert result == {"cancelled": cancelled}
        assert pi.request("received")["data"]["requests"] == [{"type": method, **wire}]
        assert pi.session.session_id is None
        pi.request("configure")
        assert pi.get_state()["sessionId"] == pi.session.session_id == "fixture"
