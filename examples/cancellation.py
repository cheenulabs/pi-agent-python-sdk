"""Leave an owned stream early: python examples/cancellation.py."""

import argparse
import asyncio

from pi_agent import AsyncPiClient


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Explain this project's design in detail without editing files.",
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        async with pi.stream(args.prompt) as stream:
            async for event in stream:
                if event.text_delta:
                    print(event.text_delta, end="", flush=True)
                    break
        # Context exit waits for queue clearing and abort, or closes an uncertain child.
        print(f"\nRun ownership released: {not pi.busy}")
        if pi.running:
            print(f"Pi streaming: {(await pi.get_state())['isStreaming']}")


if __name__ == "__main__":
    asyncio.run(main())
