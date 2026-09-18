"""Queue steering and a follow-up during a run: python examples/steering.py."""

import argparse
import asyncio

from pi_coding_agent_client import AsyncPiClient


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Inspect this project's design without changing files."
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        async with pi.stream(args.prompt) as stream:
            redirected = False
            async for event in stream:
                if event.type == "agent_start" and not redirected:
                    redirected = True
                    # Pi controls queue timing. A very fast run may already be done.
                    state = await pi.get_state()
                    if state["isStreaming"]:
                        await pi.steer("Focus on the public interfaces.")
                        await pi.follow_up("Then give three concrete improvement suggestions.")
                if event.text_delta is not None:
                    print(event.text_delta, end="", flush=True)
            result = await stream.result()
        print(f"\nStop reason: {result.stop_reason}")


if __name__ == "__main__":
    asyncio.run(main())
