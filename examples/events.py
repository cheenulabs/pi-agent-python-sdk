"""Observe lifecycle events alongside a run: python examples/events.py."""

import argparse
import asyncio
from contextlib import suppress

from pi_agent import AsyncPiClient


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Explain this project's structure without editing files."
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        # Enter before submitting work; there is no subscription history.
        async with pi.events() as events:

            async def observe() -> None:
                async for event in events:
                    if event.type in {"agent_start", "agent_settled", "tool_execution_start"}:
                        print(f"Event: {event.type}")

            observer = asyncio.create_task(observe())
            try:
                result = await pi.run(args.prompt)
            finally:
                # This observer is for live progress, not an archival event log.
                observer.cancel()
                with suppress(asyncio.CancelledError):
                    await observer
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
