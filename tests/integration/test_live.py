"""Optional real-model smoke checks. Never enabled by credential presence alone."""

import os

import pytest

from pi_coding_agent_client import AsyncPiClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PI_CLIENT_LIVE_TESTS") != "1",
        reason="Explicitly set PI_CLIENT_LIVE_TESTS=1 to run configured real-model smoke tests",
    ),
]


async def test_configured_real_model_prompt_stream_and_tool(tmp_path):
    # The opt-in caller owns normal Pi configuration and credentials. The
    # project and requested tool work remain synthetic and isolated here.
    (tmp_path / "smoke.txt").write_text("synthetic smoke content\n", encoding="utf-8")
    async with AsyncPiClient(
        cwd=tmp_path,
        provider=os.environ.get("PI_CLIENT_LIVE_PROVIDER"),
        model=os.environ.get("PI_CLIENT_LIVE_MODEL"),
        no_session=True,
        extra_args=["--tools", "read"],
    ) as pi:
        result = await pi.run("Reply with the word ready.", timeout=120)
        assert result.text
        async with pi.stream(
            "Read smoke.txt using the read tool and report its content.", timeout=120
        ) as stream:
            kinds = {event.type async for event in stream}
            result = await stream.result()
        assert "tool_execution_start" in kinds
        assert "message_update" in kinds
        assert "synthetic smoke content" in result.text
