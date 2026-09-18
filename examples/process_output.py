"""Forward and collect RPC-process stderr: python examples/process_output.py."""

import asyncio
import sys

from pi_agent import AsyncPiClient


async def main() -> None:
    pi = AsyncPiClient()
    collected = bytearray()  # Caller chooses retention; this example keeps all bytes.
    async with pi.observe() as output:

        async def consume() -> None:
            async for record in output:
                # Slow destinations should use a caller-owned worker or larger limits.
                sys.stderr.buffer.write(record.data)
                sys.stderr.buffer.flush()
                collected.extend(record.data)

        consumer = asyncio.create_task(consume())
        primary_error: BaseException | None = None
        try:
            await pi.start()
            print(f"Pi session: {pi.session.session_id}")
        except BaseException as error:
            primary_error = error
            raise
        finally:
            await pi.aclose()
            try:
                await consumer
            except Exception as error:
                if primary_error is None:
                    raise
                primary_error.add_note(
                    f"Output consumer also failed: {type(error).__name__}: {error}"
                )
        print(f"Collected {len(collected)} stderr bytes; complete: {output.status.complete}")
        # Decode once after collection, or use an incremental decoder while streaming.
        _text = collected.decode("utf-8", errors="replace")


if __name__ == "__main__":
    asyncio.run(main())
