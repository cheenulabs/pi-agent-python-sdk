"""Show text, thinking, tool progress and raw events: python examples/stream.py."""

import argparse
import asyncio
import json

from pi_agent import AsyncPiClient, Event


def display(event: Event) -> None:
    raw = event.raw
    update = raw.get("assistantMessageEvent")
    if event.text_delta is not None:
        print(event.text_delta, end="", flush=True)
    elif (
        event.type == "message_update"
        and isinstance(update, dict)
        and update.get("type") == "thinking_delta"
    ):
        print(f"\n[thinking] {update.get('delta', '')}", flush=True)
    elif event.type in {"tool_execution_start", "tool_execution_update", "tool_execution_end"}:
        # Original args, partialResult, result, isError, IDs and future fields stay available.
        print(f"\n[tool] {json.dumps(raw)}", flush=True)
    else:
        # Include unfamiliar event types and metadata instead of dropping them.
        print(f"\n[event] {json.dumps(raw)}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Explain this project's entry points without editing files."
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        async with pi.stream(args.prompt) as stream:
            async for event in stream:
                # Await application I/O here; keep blocking destinations off the client loop.
                await asyncio.to_thread(display, event)
            result = await stream.result()
        print(f"\nStop reason: {result.stop_reason}")
        print(f"Elapsed seconds: {result.elapsed_seconds:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
