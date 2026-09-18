"""Stream text and then get the final result: python examples/stream.py."""

import argparse
import asyncio

from pi_agent import AsyncPiClient


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Explain this project's entry points without editing files."
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        async with pi.stream(args.prompt) as stream:
            async for event in stream:
                if event.text_delta is not None:
                    print(event.text_delta, end="", flush=True)
            result = await stream.result()
        print(f"\nStop reason: {result.stop_reason}")
        print(f"Elapsed seconds: {result.elapsed_seconds:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
