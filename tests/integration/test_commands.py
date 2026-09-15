"""Exercise every explicit command against Pi, with no provider network calls."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from pi_coding_agent_client.client import AsyncPiClient
from pi_coding_agent_client.errors import PiCommandError
from pi_coding_agent_client.types import Event, ExtensionUIRequest

pytestmark = pytest.mark.integration


async def complete_prompt(client: AsyncPiClient, text: str = "synthetic answer") -> list[Event]:
    """Use acceptance/events so command tests are independent of run helpers."""
    await client.prompt("/fixture-script " + json.dumps([{"text": text}]))
    async with client.events() as events, asyncio.timeout(10):
        receipt = await client.prompt("synthetic question")
        assert receipt["success"] is True
        result = []
        async for event in events:
            result.append(event)
            if event.type == "agent_settled":
                return result
    raise AssertionError("Pi ended without settlement")


async def test_state_models_thinking_and_configuration(pi_client: AsyncPiClient) -> None:
    state = await pi_client.get_state()
    assert state["model"]["provider"] == "python-fixture"
    assert state["isStreaming"] is False
    assert state["sessionId"] == pi_client.session.session_id
    models = await pi_client.get_available_models()
    assert {m["id"] for m in models if m["provider"] == "python-fixture"} == {
        "fixture", "fixture-other"
    }
    selected = await pi_client.set_model("python-fixture", "fixture-other")
    assert selected["id"] == "fixture-other"
    cycled = await pi_client.cycle_model()
    assert cycled is not None and cycled["model"]["provider"] == "python-fixture"
    levels = await pi_client.get_available_thinking_levels()
    assert "off" in levels and "high" in levels
    await pi_client.set_thinking_level("high")
    assert (await pi_client.get_state())["thinkingLevel"] == "high"
    assert await pi_client.cycle_thinking_level() in levels
    await pi_client.set_steering_mode("all")
    await pi_client.set_follow_up_mode("one-at-a-time")
    await pi_client.set_auto_compaction(True)
    state = await pi_client.get_state()
    assert state["steeringMode"] == "all"
    assert state["followUpMode"] == "one-at-a-time"
    assert state["autoCompactionEnabled"] is True
    await pi_client.set_auto_compaction(False)
    await pi_client.set_auto_retry(False)
    await pi_client.set_auto_retry(True)
    await pi_client.abort_retry()
    with pytest.raises(PiCommandError):
        await pi_client.set_model("python-fixture", "not-a-fixture-model")


async def test_prompt_queue_and_idle_abort(pi_client: AsyncPiClient) -> None:
    await pi_client.steer("synthetic steering", images=[])
    await pi_client.follow_up("synthetic follow-up", images=[])
    assert (await pi_client.get_state())["pendingMessageCount"] == 2
    assert await pi_client.clear_queue() == {
        "steering": ["synthetic steering"],
        "followUp": ["synthetic follow-up"],
    }
    assert await pi_client.clear_queue() == {"steering": [], "followUp": []}
    await pi_client.abort()
    assert (await pi_client.prompt("fixture handled", images=[]))["success"] is True
    assert (await pi_client.get_state())["messageCount"] == 0
    events = await complete_prompt(pi_client)
    assert events[-1].type == "agent_settled"
    assert "".join(e.text_delta or "" for e in events) == "synthetic answer"


async def test_history_entries_stats_and_compaction(pi_client: AsyncPiClient) -> None:
    assert await pi_client.get_last_assistant_text() is None
    assert await pi_client.get_messages() == []
    initial = await pi_client.get_entries()
    assert initial["entries"]
    assert isinstance(initial["leafId"], str)
    await complete_prompt(pi_client)
    assert await pi_client.get_last_assistant_text() == "synthetic answer"
    assert [m["role"] for m in await pi_client.get_messages()] == ["user", "assistant"]
    stats = await pi_client.get_session_stats()
    assert stats["userMessages"] == 1 and stats["assistantMessages"] == 1
    assert stats["sessionId"] == pi_client.session.session_id
    entries = await pi_client.get_entries(since=initial["leafId"])
    assert any(e["type"] == "message" for e in entries["entries"])
    tree = await pi_client.get_tree()
    assert tree["leafId"] == entries["leafId"]
    assert tree["tree"]
    commands = await pi_client.get_commands()
    fixture = next(c for c in commands if c["name"] == "fixture-script")
    assert fixture["source"] == "extension" and fixture["sourceInfo"]
    await pi_client.set_session_name("Synthetic \u2028session\u2029name")
    assert pi_client.session.session_name == "Synthetic \u2028session\u2029name"
    async with pi_client.events() as events:
        compact = await pi_client.compact(custom_instructions="synthetic instructions")
        assert compact["summary"] == "Synthetic offline compaction summary"
        async with asyncio.timeout(10):
            observed = []
            async for event in events:
                observed.append(event.type)
                if event.type == "compaction_end":
                    break
        assert "compaction_start" in observed
    assert any(e["type"] == "compaction" for e in (await pi_client.get_entries())["entries"])


async def test_bash_and_export(pi_client: AsyncPiClient, tmp_path: Path) -> None:
    async with pi_client.events() as events:
        result = await pi_client.bash("echo synthetic-bash", exclude_from_context=True)
        assert result["exitCode"] == 0 and result["output"].strip() == "synthetic-bash"
        async with asyncio.timeout(10):
            event = await anext(events)
        assert event.type == "bash_execution_update"
        assert "synthetic-bash" in event.raw["delta"]
    await pi_client.abort_bash()
    messages = await pi_client.get_messages()
    assert messages[-1]["role"] == "bashExecution"
    assert messages[-1]["excludeFromContext"] is True
    await complete_prompt(pi_client)
    output = tmp_path / "synthetic-session.html"
    exported = await pi_client.export_html(output_path=str(output))
    assert Path(exported) == output
    html = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    encoded = re.search(
        r'<script id="session-data" type="application/json">([A-Za-z0-9+/=]+)</script>', html
    )
    assert encoded is not None
    assert "synthetic answer" in base64.b64decode(encoded[1]).decode("utf-8")


async def test_session_fork_clone_switch_and_veto(pi_client: AsyncPiClient) -> None:
    await complete_prompt(pi_client)
    original = pi_client.session.session_id
    original_path = (await pi_client.get_state())["sessionFile"]
    forks = await pi_client.get_fork_messages()
    assert forks[0]["text"] == "synthetic question"
    await pi_client.prompt("/fixture-veto on")
    assert await pi_client.new_session() == {"cancelled": True}
    assert await pi_client.switch_session(original_path) == {"cancelled": True}
    assert await pi_client.fork(forks[0]["entryId"]) == {"cancelled": True}
    assert pi_client.session.session_id == original
    await pi_client.prompt("/fixture-veto off")
    assert await pi_client.clone() == {"cancelled": False}
    assert pi_client.session.session_id != original
    assert await pi_client.get_last_assistant_text() == "synthetic answer"
    assert await pi_client.switch_session(original_path) == {"cancelled": False}
    assert pi_client.session.session_id == original
    fork = await pi_client.fork(forks[0]["entryId"])
    assert fork == {"cancelled": False, "text": "synthetic question"}
    assert pi_client.session.session_id != original
    assert await pi_client.new_session(parent_session=original_path) == {"cancelled": False}
    assert await pi_client.get_last_assistant_text() is None


async def test_persistence_across_owned_processes(
    pi_client_factory: Callable[..., AsyncPiClient],
) -> None:
    async with pi_client_factory() as first:
        await complete_prompt(first, "persisted synthetic answer")
        state = await first.get_state()
    async with pi_client_factory(session=state["sessionFile"]) as second:
        assert (await second.get_state())["sessionId"] == state["sessionId"]
        assert await second.get_last_assistant_text() == "persisted synthetic answer"


@pytest.mark.parametrize("method", ["select", "confirm", "input", "editor"])
async def test_dialog_replies(
    pi_client_factory: Callable[..., AsyncPiClient], method: str
) -> None:
    seen: list[ExtensionUIRequest] = []

    async def handler(request: ExtensionUIRequest) -> str | bool | None:
        seen.append(request)
        return True if request["method"] == "confirm" else "one"

    async with pi_client_factory(ui_handler=handler) as client:
        async with client.events() as events:
            await client.prompt("/fixture-ui " + method)
            async with asyncio.timeout(10):
                async for event in events:
                    if event.raw.get("method") == "notify":
                        assert json.loads(event.raw["message"])["result"] == (
                            True if method == "confirm" else "one"
                        )
                        break
        assert any(request["method"] == method for request in seen)


async def test_display_events_and_unhandled_dialog(pi_client: AsyncPiClient) -> None:
    async with pi_client.events() as events:
        await pi_client.prompt("/fixture-ui display")
        async with asyncio.timeout(10):
            methods = {(await anext(events)).raw["method"] for _ in range(5)}
        assert methods == {"setStatus", "setWidget", "setTitle", "set_editor_text", "notify"}
        await pi_client.prompt("/fixture-ui input")
        async with asyncio.timeout(10):
            async for event in events:
                if event.raw.get("method") == "notify":
                    assert json.loads(event.raw["message"]) == {"result": None}
                    break


async def test_extension_error_remains_an_event(pi_client: AsyncPiClient) -> None:
    async with pi_client.events() as events:
        receipt = await pi_client.prompt("/fixture-error")
        assert receipt["success"] is True
        async with asyncio.timeout(10):
            event = await anext(events)
        assert event.type == "extension_error"
        assert "synthetic fixture error" in event.raw["error"]
