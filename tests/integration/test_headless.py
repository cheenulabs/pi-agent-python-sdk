"""Real Pi accepts headless arguments and reports incomplete runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pi_agent import PiIncompleteRunError, headless_args
from pi_agent.client import AsyncPiClient

from .control import set_responses

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).with_name("fixture.ts")


@pytest.fixture
def headless_options(pi_options: dict[str, Any]) -> dict[str, Any]:
    project = Path(pi_options["cwd"])
    config = Path(pi_options["env"]["PI_CODING_AGENT_DIR"])
    # Discoverable resources that headless_args must not load.
    for root in (config, project / ".pi"):
        (root / "prompts").mkdir(parents=True)
        (root / "prompts/discovered.md").write_text("Discovered template", encoding="utf-8")
    (project / "AGENTS.md").write_text("Discovered context", encoding="utf-8")
    return {**pi_options, "extra_args": headless_args(extensions=[FIXTURE])}


async def test_headless_client_loads_only_named_extension(headless_options):
    async with AsyncPiClient(**headless_options) as pi:
        commands = await pi.get_commands()
        assert {command["source"] for command in commands} == {"extension"}
        assert "discovered" not in {command["name"] for command in commands}
        set_responses(pi, [{"text": "headless answer"}])
        result = (await pi.run("hello", timeout=10)).raise_for_incomplete()
        assert result.text == "headless answer"


async def test_truncated_run_is_incomplete(headless_options):
    async with AsyncPiClient(**headless_options) as pi:
        set_responses(pi, [{"text": "cut off", "stopReason": "length"}])
        result = await pi.run("hello", timeout=10)
        assert result.stop_reason == "length"
        with pytest.raises(PiIncompleteRunError) as caught:
            result.raise_for_incomplete()
        assert caught.value.result.text == "cut off"
        assert caught.value.reason == "stop_reason"
