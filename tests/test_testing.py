"""The public scripted fake drives the real clients without a model."""

from __future__ import annotations

import os

import pytest

from pi_agent import AsyncPiClient, PiClient, PiCommandError, PiRunError
from pi_agent.testing import FakePi, FakeReply


def test_sync_run_returns_scripted_replies_and_records_prompts() -> None:
    replies = ["Hello!", FakeReply("cut off", stop_reason="length")]
    with FakePi(replies) as fake:
        with PiClient(executable=fake.executable) as pi:
            assert pi.compatibility == "tested"
            first = pi.run("Hi")
            assert (first.text, first.stop_reason) == ("Hello!", "stop")
            assert first.session.session_id == "fake-session"
            assert pi.run("Again").stop_reason == "length"
            assert pi.get_last_assistant_text() == "cut off"
            assert [m["role"] for m in pi.get_messages()] == ["user", "assistant"] * 2
        assert fake.prompts() == ["Hi", "Again"]
        assert {"get_state", "prompt"} <= {r["type"] for r in fake.requests()}


async def test_async_stream_yields_text_and_usage() -> None:
    reply = FakeReply("streamed", thinking="hmm", usage={"input": 7, "output": 3})
    with FakePi([reply], provider="acme", model="m1") as fake:
        async with AsyncPiClient(executable=fake.executable) as pi:
            async with pi.stream("Go") as stream:
                deltas = [event.text_delta async for event in stream if event.text_delta]
                result = await stream.result()
    assert deltas == ["streamed"]
    assert result.text == "streamed"
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)
    assert result.messages[-1]["provider"] == "acme"


def test_error_reply_raises_run_error_with_partial_result() -> None:
    reply = FakeReply("partial", stop_reason="error", error_message="overloaded")
    with FakePi([reply]) as fake, PiClient(executable=fake.executable) as pi:
        with pytest.raises(PiRunError) as caught:
            pi.run("Hi")
    assert caught.value.result.text == "partial"
    assert caught.value.result.messages[-1]["errorMessage"] == "overloaded"


def test_exhausted_script_and_unsupported_commands_fail_clearly() -> None:
    with FakePi(["only"]) as fake, PiClient(executable=fake.executable) as pi:
        pi.run("one")
        with pytest.raises(PiCommandError) as exhausted:
            pi.run("two")
        assert "no scripted reply" in exhausted.value.error
        with pytest.raises(PiCommandError) as unsupported:
            pi.set_session_name("name")
        assert "does not implement 'set_session_name'" in unsupported.value.error


def test_runs_with_an_explicit_minimal_environment() -> None:
    with FakePi(["isolated"]) as fake:
        env = {"PATH": os.environ.get("PATH", "")}
        with PiClient(executable=fake.executable, env=env, inherit_env=False) as pi:
            assert pi.run("Hi").text == "isolated"


def test_each_client_starts_from_the_first_reply() -> None:
    with FakePi(["first"]) as fake:
        for _ in range(2):
            with PiClient(executable=fake.executable) as pi:
                assert pi.run("Hi").text == "first"
        assert fake.prompts() == ["Hi", "Hi"]


def test_requires_an_active_context() -> None:
    fake = FakePi()
    with pytest.raises(RuntimeError, match="context manager"):
        _ = fake.executable
    with fake:
        with pytest.raises(RuntimeError, match="already active"):
            fake.__enter__()
    with pytest.raises(RuntimeError):
        fake.requests()
