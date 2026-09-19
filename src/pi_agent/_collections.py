"""Bounded observation through the next settlement, without run ownership."""

from __future__ import annotations

import asyncio
import json

from ._events import EventSubscription
from .errors import PiProcessError, PiResultOverflow, PiTimeoutError
from .types import Event, Limits, _validate_timeout


def deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    _validate_timeout(timeout, "Collection timeout")
    return asyncio.get_running_loop().time() + timeout


def start_collection(
    subscription: EventSubscription,
    limits: Limits,
    *,
    timeout: float | None,
    retain: bool,
) -> asyncio.Task[list[Event] | None]:
    expires = deadline(timeout)
    # Register now, not when the task first runs: callers may submit immediately.
    subscription._enter()

    async def consume() -> list[Event] | None:
        events: list[Event] = []
        size = 0
        timer = asyncio.timeout_at(expires)
        try:
            async with timer:
                async for event in subscription:
                    if retain:
                        size += len(json.dumps(event.raw).encode("utf-8"))
                        if (
                            len(events) >= limits.collection_event_count
                            or size > limits.collection_event_bytes
                        ):
                            raise PiResultOverflow("Event collection exceeded its count/byte limit")
                        events.append(event)
                    if event.type == "agent_settled":
                        return events if retain else None
                raise PiProcessError("Event collection closed before settlement")
        except TimeoutError as exc:
            if not timer.expired():
                raise
            raise PiTimeoutError("Event collection deadline elapsed", uncertain=False) from exc
        finally:
            await subscription.aclose()

    task = asyncio.create_task(consume(), name="pi-event-collection")
    # Cancellation before the task's first instruction cannot run its finally.
    task.add_done_callback(lambda _: subscription._discard())
    return task
