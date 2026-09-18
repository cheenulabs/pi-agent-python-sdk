"""Observe real Pi extension initialization without invoking a provider."""

import pytest

from pi_agent import AsyncPiClient

pytestmark = pytest.mark.integration


async def test_extension_notification_before_readiness(pi_options, tmp_path):
    extension = tmp_path / "startup.ts"
    extension.write_text("""export default function(pi) {
      pi.on("session_start", (_event, ctx) => ctx.ui.notify("startup fixture", "info"));
    }""")
    options = {
        **pi_options,
        "extra_args": [*pi_options["extra_args"], "--extension", str(extension)],
    }
    pi = AsyncPiClient(**options)
    try:
        async with pi.events() as events:
            await pi.start()
            event = await anext(events)
            assert event.type == "extension_ui_request"
            assert event.raw["method"] == "notify"
            assert event.raw["message"] == "startup fixture"
    finally:
        await pi.aclose()
