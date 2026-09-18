"""Real runtime settlement, cancellation, retries, and extension interaction."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pi_coding_agent_client.client import AsyncPiClient
from pi_coding_agent_client.errors import (
    PiBusyError,
    PiCommandError,
    PiRunError,
    PiRunOwnershipError,
    PiRunStartTimeout,
    PiTimeoutError,
)
from pi_coding_agent_client.types import Event, Limits

from .control import set_responses

pytestmark = pytest.mark.integration


async def script(client: AsyncPiClient, *steps: dict[str, Any]) -> None:
    set_responses(client, list(steps))


async def test_delayed_handled_input_cannot_be_misattributed_to_owned_run(pi_client):
    set_responses(pi_client, [{"text": "answer to earlier input"}])
    await pi_client.prompt("fixture delayed")
    state = await pi_client.get_state()
    assert not state["isStreaming"] and state["pendingMessageCount"] == 0
    with pytest.raises(PiRunOwnershipError):
        await pi_client.run("a different question")
    async with pi_client.events() as events:
        await pi_client.prompt("/fixture-release-delayed")
        observed = []
        async with asyncio.timeout(10):
            async for event in events:
                observed.append(event)
                if event.type == "agent_settled":
                    break
    assert any(event.type == "agent_start" for event in observed)
    assert "".join(event.text_delta or "" for event in observed) == "answer to earlier input"


async def wait_event(events: Any, kind: str) -> Event:
    async with asyncio.timeout(10):
        async for event in events:
            if event.type == kind:
                return event
    raise AssertionError(f"No {kind} before event subscription closed")


async def test_stream_text_thinking_tool_and_usage(pi_client: AsyncPiClient) -> None:
    await script(
        pi_client,
        {"thinking": "synthetic reasoning", "tool": "fixture_echo", "arguments": {"text": "echo"}},
        {"text": "final answer"},
    )
    async with pi_client.stream("synthetic question", timeout=10) as stream:
        events = [event async for event in stream]
        result = await stream.result()
        assert await stream.result() is result
    assert result.text == "final answer"
    assert result.stop_reason == "stop"
    assert result.session.session_id == pi_client.session.session_id
    assert result.elapsed_seconds > 0
    kinds = {event.type for event in events}
    assert {"tool_execution_start", "tool_execution_update", "tool_execution_end"} <= kinds
    assert events[-1].type == "agent_settled"
    assert "".join(event.text_delta or "" for event in events) == result.text
    assert any(
        event.raw.get("assistantMessageEvent", {}).get("type") == "thinking_delta"
        for event in events
    )
    assistants = [message for message in result.messages if message["role"] == "assistant"]
    assert result.usage is not None
    assert result.usage.assistant_messages == len(assistants) == 2
    assert result.usage.total_tokens == sum(
        message["usage"]["totalTokens"] for message in assistants
    )
    assert result.usage.cost == 0


async def test_retry_waits_for_recovery_and_one_settlement(pi_client: AsyncPiClient) -> None:
    await script(
        pi_client,
        {"stopReason": "error", "error": "overloaded_error"},
        {"text": "recovered answer"},
    )
    async with pi_client.stream("synthetic question", timeout=10) as stream:
        events = [event async for event in stream]
        result = await stream.result()
    kinds = [event.type for event in events]
    assert kinds.count("agent_end") == 2
    assert kinds.count("agent_settled") == 1
    assert (
        kinds.index("auto_retry_start")
        < kinds.index("auto_retry_end")
        < kinds.index("agent_settled")
    )
    assert result.text == "recovered answer"
    assert result.usage is not None and result.usage.assistant_messages == 2


async def test_steer_and_follow_up_settle_after_queued_turns(pi_client: AsyncPiClient) -> None:
    await script(
        pi_client,
        {"tool": "fixture_echo", "arguments": {"text": "released", "wait": "tool-gate"}},
        {"text": "steered answer"},
        {"text": "follow-up answer"},
    )
    async with pi_client.events() as events:
        task = asyncio.create_task(pi_client.run("synthetic initial", timeout=10))
        try:
            await wait_event(events, "tool_execution_update")
            with pytest.raises(PiBusyError):
                await pi_client.new_session()
            with pytest.raises(PiBusyError):
                await pi_client.run("competing input")
            await pi_client.steer("synthetic steering")
            await pi_client.follow_up("synthetic follow-up")
            await pi_client.prompt("/fixture-release tool-gate", streaming_behavior="steer")
            result = await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert result.text == "follow-up answer"
    users = [m["content"][0]["text"] for m in result.messages if m["role"] == "user"]
    assert users == ["synthetic initial", "synthetic steering", "synthetic follow-up"]
    assert not pi_client.busy
    assert (await pi_client.get_state())["pendingMessageCount"] == 0


@pytest.mark.parametrize("operation", ["task", "context", "timeout"])
async def test_owned_cancellation_clears_queue_and_keeps_client_usable(
    pi_client: AsyncPiClient, operation: str
) -> None:
    await script(
        pi_client,
        {"tool": "fixture_echo", "arguments": {"text": "waiting", "wait": "cancel-gate"}},
    )
    async with pi_client.events() as events:
        if operation == "context":
            async with pi_client.stream("synthetic cancel", timeout=10):
                await wait_event(events, "tool_execution_update")
                await pi_client.follow_up("must be discarded")
        else:
            task = asyncio.create_task(
                pi_client.run("synthetic cancel", timeout=1 if operation == "timeout" else 10)
            )
            try:
                await wait_event(events, "tool_execution_update")
                await pi_client.follow_up("must be discarded")
                if operation == "task":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    with pytest.raises(PiTimeoutError):
                        await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    assert pi_client.running and not pi_client.busy
    state = await pi_client.get_state()
    assert not state["isStreaming"] and state["pendingMessageCount"] == 0
    await script(pi_client, {"text": "usable after cancellation"})
    assert (await pi_client.run("next input", timeout=10)).text == "usable after cancellation"


@pytest.mark.parametrize("message", ["fixture handled", "/fixture-ui display"])
async def test_handled_prompt_start_deadline_closes_owned_process(
    pi_client_factory: Callable[..., AsyncPiClient], message: str
) -> None:
    async with pi_client_factory(limits=Limits(run_start_timeout=0.15)) as client:
        with pytest.raises(PiRunStartTimeout) as error:
            await client.run(message, timeout=10)
        assert error.value.uncertain is True
        assert not client.running and not client.busy


@pytest.mark.parametrize("reason", ["error", "aborted"])
async def test_final_failure_exposes_this_runs_partial_result(
    pi_client: AsyncPiClient, reason: str
) -> None:
    await script(pi_client, {"text": "previous answer"})
    await pi_client.run("prior input", timeout=10)
    await pi_client.set_auto_retry(False)
    await script(
        pi_client,
        {"text": "partial new answer", "stopReason": reason, "error": "synthetic failure"},
    )
    with pytest.raises(PiRunError) as error:
        await pi_client.run("current input", timeout=10)
    assert error.value.result.stop_reason == reason
    assert error.value.result.text == "partial new answer"
    assert "previous answer" not in str(error.value.result.messages)


async def test_result_refreshes_session_changed_inside_extension(pi_client: AsyncPiClient) -> None:
    original = pi_client.session.session_id
    result = await pi_client.run("/fixture-new-session-and-run", timeout=10)
    assert result.text == "answer from new session"
    assert result.session.session_id != original
    assert result.session.session_id == (await pi_client.get_state())["sessionId"]


async def test_abort_retry_during_backoff(
    pi_options: dict[str, Any], pi_client_factory: Callable[..., AsyncPiClient]
) -> None:
    config = Path(pi_options["env"]["PI_CODING_AGENT_DIR"]) / "settings.json"
    settings = json.loads(config.read_text())
    settings["retry"]["baseDelayMs"] = 30_000
    config.write_text(json.dumps(settings))
    async with pi_client_factory() as client:
        await script(
            client,
            {"stopReason": "error", "error": "overloaded_error"},
            {"text": "unreached"},
        )
        async with client.events() as events:
            task = asyncio.create_task(client.run("synthetic retry", timeout=10))
            try:
                await wait_event(events, "auto_retry_start")
                await client.abort_retry()
                with pytest.raises(PiRunError):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        assert not client.busy


async def test_abort_manual_compaction_and_reject_concurrent_prompt(
    pi_client: AsyncPiClient,
) -> None:
    await script(pi_client, {"text": "history to compact"})
    await pi_client.run("synthetic input", timeout=10)
    await pi_client.prompt("/fixture-compact-gate compact-gate")
    async with pi_client.events() as events:
        task = asyncio.create_task(pi_client.compact(timeout=10))
        try:
            await wait_event(events, "compaction_start")
            with pytest.raises(PiCommandError) as error:
                await pi_client.prompt("must be rejected")
            assert "compaction" in error.value.error
            await pi_client.abort()
            with pytest.raises(PiCommandError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert not (await pi_client.get_state())["isCompacting"]


async def test_native_summarization_retry(pi_client: AsyncPiClient) -> None:
    await script(pi_client, {"text": "history to summarize"})
    await pi_client.run("synthetic history", timeout=10)
    await pi_client.prompt("/fixture-native-compaction on")
    await script(
        pi_client,
        {"stopReason": "error", "error": "terminated"},
        {"text": "recovered synthetic summary"},
    )
    async with pi_client.events() as events:
        result = await pi_client.compact(timeout=10)
        assert "recovered synthetic summary" in result["summary"]
        observed = []
        async with asyncio.timeout(10):
            async for event in events:
                observed.append(event.type)
                if event.type == "compaction_end":
                    break
    assert "summarization_retry_scheduled" in observed
    assert "summarization_retry_attempt_start" in observed
    assert "summarization_retry_finished" in observed


async def test_context_overflow_compaction_recovery(pi_client: AsyncPiClient) -> None:
    await script(pi_client, {"text": "prior history"})
    await pi_client.run("synthetic history", timeout=10)
    await pi_client.set_auto_compaction(True)
    await script(
        pi_client,
        {"stopReason": "error", "error": "maximum context length exceeded"},
        {"text": "recovered after compaction"},
    )
    async with pi_client.stream("overflow input", timeout=10) as stream:
        events = [event async for event in stream]
        result = await stream.result()
    assert result.text == "recovered after compaction"
    compactions = [event for event in events if event.type == "compaction_end"]
    assert compactions and compactions[0].raw["reason"] == "overflow"
    assert compactions[0].raw["willRetry"] is True
    assert sum(event.type == "agent_settled" for event in events) == 1


async def test_abort_bash_after_real_output(pi_client: AsyncPiClient) -> None:
    command = "node -e \"console.log('fixture-bash-ready'); setInterval(() => {}, 1000)\""
    async with pi_client.events() as events:
        task = asyncio.create_task(pi_client.bash(command, exclude_from_context=True, timeout=10))
        try:
            ready = await wait_event(events, "bash_execution_update")
            assert "fixture-bash-ready" in ready.raw["delta"]
            await pi_client.abort_bash()
            result = await task
            assert result["cancelled"] is True
        finally:
            if not task.done():
                await pi_client.abort_bash()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
