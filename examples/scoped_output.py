"""Drain one scoped RPC observation and reuse Pi: python examples/scoped_output.py."""

import asyncio

from pi_agent import AsyncPiClient, ProcessOutput


async def main() -> None:
    async with AsyncPiClient() as pi:
        records: list[ProcessOutput] = []  # Caller owns retention and export policy.
        async with pi.observe(stderr=False, rpc=True) as output:

            async def collect() -> None:
                async for record in output:
                    records.append(record)  # Retain the SDK's receipt timestamp.

            consumer = asyncio.create_task(collect())
            try:
                print((await pi.run("Say hello briefly.")).text)
            finally:
                await output.stop()
                await consumer
            assert output.status.end_reason == "stopped"
            assert not output.status.lost and output.status.error is None
            assert not output.status.complete  # This covers a scope, not the whole process.
        print(f"Captured {len(records)} RPC records")
        print((await pi.run("Say goodbye briefly.")).text)


if __name__ == "__main__":
    asyncio.run(main())
