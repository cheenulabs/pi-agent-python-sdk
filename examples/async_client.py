"""Use the async client: python examples/async_client.py 'Describe this project'."""

import argparse
import asyncio

from pi_coding_agent_client import AsyncPiClient


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Explain this project's purpose without changing files."
    )
    args = parser.parse_args()
    async with AsyncPiClient() as pi:
        result = await pi.run(args.prompt)
        print(result.text)
        print(f"Stop reason: {result.stop_reason}")


if __name__ == "__main__":
    asyncio.run(main())
