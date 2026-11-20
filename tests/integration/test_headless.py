"""Real Pi accepts headless arguments, loads only named resources, and reports
incomplete runs."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pi_agent import PiIncompleteRunError, headless_args
from pi_agent.client import AsyncPiClient

from .control import set_responses

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).with_name("fixture.ts")
PROMPT_CAPTURE = Path(__file__).with_name("prompt_capture.ts")
# Present in the built-in prompt of every supported Pi version.
BUILT_IN = "inside pi, a coding agent harness"
SYSTEM_MARKER = "synthetic SYSTEM.md marker"
APPEND_MARKER = "synthetic APPEND_SYSTEM.md marker"

Options = Callable[..., dict[str, Any]]


@pytest.fixture
def headless_options(pi_options: dict[str, Any], tmp_path: Path) -> Options:
    project = Path(pi_options["cwd"])
    config = Path(pi_options["env"]["PI_CODING_AGENT_DIR"])
    # Discoverable resources that headless_args must not load by default.
    for root in (config, project / ".pi"):
        (root / "prompts").mkdir(parents=True)
        (root / "prompts/discovered.md").write_text("Discovered template", encoding="utf-8")
        (root / "SYSTEM.md").write_text(SYSTEM_MARKER, encoding="utf-8")
        (root / "APPEND_SYSTEM.md").write_text(APPEND_MARKER, encoding="utf-8")
    (project / "AGENTS.md").write_text("Discovered context", encoding="utf-8")
    version = subprocess.run(
        [*pi_options["executable"], "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    # Pi before 1.3.0 has no --no-mcp option (and no built-in MCP to disable).
    mcp = tuple(map(int, version.split("."))) < (1, 3, 0)
    env = {**pi_options["env"], "PI_FIXTURE_PROMPT_CAPTURE": str(tmp_path / "prompt.txt")}

    def build(**overrides: Any) -> dict[str, Any]:
        arguments = headless_args(extensions=[FIXTURE, PROMPT_CAPTURE], mcp=mcp, **overrides)
        return {**pi_options, "env": env, "extra_args": arguments}

    return build


async def _system_prompt(options: dict[str, Any]) -> str:
    async with AsyncPiClient(**options) as pi:
        set_responses(pi, [{"text": "answer"}])
        await pi.run("hello", timeout=10)
    capture = Path(options["env"]["PI_FIXTURE_PROMPT_CAPTURE"])
    return await asyncio.to_thread(capture.read_text, encoding="utf-8")


async def test_headless_client_loads_only_named_extension(headless_options):
    async with AsyncPiClient(**headless_options()) as pi:
        commands = await pi.get_commands()
        assert {command["source"] for command in commands} == {"extension"}
        assert "discovered" not in {command["name"] for command in commands}
        set_responses(pi, [{"text": "headless answer"}])
        result = (await pi.run("hello", timeout=10)).raise_for_incomplete()
        assert result.text == "headless answer"


async def test_default_prompt_ignores_prompt_files_and_context(headless_options):
    prompt = await _system_prompt(headless_options())
    assert BUILT_IN in prompt
    assert SYSTEM_MARKER not in prompt
    assert APPEND_MARKER not in prompt
    assert "Discovered context" not in prompt


async def test_prompt_files_opt_in_loads_agent_directory_files(headless_options):
    prompt = await _system_prompt(headless_options(prompt_files=True))
    # SYSTEM.md replaces the built-in prompt; APPEND_SYSTEM.md extends it.
    # Only the agent-directory copies load: project files remain untrusted.
    assert prompt.count(SYSTEM_MARKER) == 1
    assert prompt.count(APPEND_MARKER) == 1
    assert BUILT_IN not in prompt


async def test_explicit_prompts_take_precedence_over_prompt_files(headless_options):
    prompt = await _system_prompt(
        headless_options(
            prompt_files=True,
            system_prompt="Caller base prompt.",
            append_system_prompt=["Caller addendum."],
        )
    )
    assert "Caller base prompt." in prompt
    assert "Caller addendum." in prompt
    assert SYSTEM_MARKER not in prompt
    assert APPEND_MARKER not in prompt
    assert BUILT_IN not in prompt


async def test_truncated_run_is_incomplete(headless_options):
    async with AsyncPiClient(**headless_options()) as pi:
        set_responses(pi, [{"text": "cut off", "stopReason": "length"}])
        result = await pi.run("hello", timeout=10)
        assert result.stop_reason == "length"
        with pytest.raises(PiIncompleteRunError) as caught:
            result.raise_for_incomplete()
        assert caught.value.result.text == "cut off"
        assert caught.value.reason == "stop_reason"
