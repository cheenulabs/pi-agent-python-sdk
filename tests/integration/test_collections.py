"""Thin RPC helpers against the pinned Pi runtime and an offline provider."""

import pytest

from pi_agent import PiClient

from .control import set_responses

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("prompt", ["ordinary input", "/fixture-await-run"])
async def test_async_collection_and_listener(pi_client, prompt):
    text = "x " * 10000
    set_responses(pi_client, [{"text": text}])
    seen = []
    remove = pi_client.on_event(seen.append)
    events = await pi_client.prompt_and_wait(prompt, timeout=10)
    remove()
    assert "".join(event.text_delta or "" for event in events) == text
    assert [event.raw for event in events] == [event.raw for event in seen]
    assert events[-1].type == "agent_settled"
    assert pi_client.running and not pi_client.busy


@pytest.mark.parametrize("prompt", ["ordinary input", "/fixture-await-run"])
def test_sync_collection_and_listener(pi_options, prompt):
    with PiClient(**pi_options) as pi:
        text = "x " * 10000
        set_responses(pi, [{"text": text}])
        seen = []
        remove = pi.on_event(seen.append)
        events = pi.prompt_and_wait(prompt, timeout=10)
        remove()
        assert "".join(event.text_delta or "" for event in events) == text
        assert [event.raw for event in events] == [event.raw for event in seen]
        assert events[-1].type == "agent_settled"
