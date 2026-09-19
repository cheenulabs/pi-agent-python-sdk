"""Print live text and collect the RPC events through settlement."""

import asyncio

from pi_agent import AsyncPiClient
from pi_agent.types import Event


def display(event: Event) -> None:
    if event.text_delta:
        print(event.text_delta, end="", flush=True)


async def main() -> None:
    async with AsyncPiClient() as pi:
        unsubscribe = pi.on_event(display)
        try:
            events = await pi.prompt_and_wait(
                "Explain this project without changing files.", timeout=120
            )
            print(f"\nReceived {len(events)} events through {events[-1].type}")
        finally:
            unsubscribe()


if __name__ == "__main__":
    asyncio.run(main())
