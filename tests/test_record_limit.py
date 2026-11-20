"""One record limit covers outgoing prompts and Pi's larger echoed events."""

import pytest

from pi_agent import AsyncPiClient, Limits, PiClient
from pi_agent.testing import FakePi

PROMPT = "synthetic-private-payload:" + "x" * (16 * 1024 * 1024)


def check_rejection(error):
    message = str(error.value)
    assert "Limits.max_record_bytes" in message
    assert "raise" in message
    assert "echo" in message
    assert "synthetic-private-payload" not in message


def echo_recorder(echoes):
    def record(event):
        raw = event.raw
        if event.type in {"message_start", "message_end"}:
            message = raw["message"]
        elif event.type == "agent_end":
            message = raw["messages"][0]
        else:
            return
        if message["role"] == "user":
            assert message["content"][0]["text"] == PROMPT
            echoes.append(event.type)

    return record


async def test_async_large_prompt_requires_raised_shared_limit():
    with FakePi(["answer"]) as fake:
        async with AsyncPiClient(executable=fake.executable) as pi:
            with pytest.raises(ValueError) as error:
                await pi.run(PROMPT)
            check_rejection(error)
            assert pi.running and not pi.busy
            assert fake.prompts() == []
            assert (await pi.run("normal")).text == "answer"
        async with AsyncPiClient(
            executable=fake.executable, limits=Limits(max_record_bytes=20 * 1024 * 1024)
        ) as pi:
            echoes = []
            pi.on_event(echo_recorder(echoes))
            assert (await pi.run(PROMPT)).text == "answer"
            assert echoes == ["message_start", "message_end", "agent_end"]
            assert pi.running
        assert fake.prompts() == ["normal", PROMPT]


def test_blocking_large_prompt_requires_raised_shared_limit():
    with FakePi(["answer"]) as fake:
        with PiClient(executable=fake.executable) as pi:
            with pytest.raises(ValueError) as error:
                pi.run(PROMPT)
            check_rejection(error)
            assert pi.running and not pi.busy
            assert fake.prompts() == []
            assert pi.run("normal").text == "answer"
        with PiClient(
            executable=fake.executable, limits=Limits(max_record_bytes=20 * 1024 * 1024)
        ) as pi:
            echoes = []
            pi.on_event(echo_recorder(echoes))
            assert pi.run(PROMPT).text == "answer"
            assert echoes == ["message_start", "message_end", "agent_end"]
            assert pi.running
        assert fake.prompts() == ["normal", PROMPT]
