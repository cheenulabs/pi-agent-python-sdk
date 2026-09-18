"""Bounded future-only event subscriptions; response routing never waits here."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from types import TracebackType
from typing import Generic, Self, TypeVar

from .errors import PiSubscriptionOverflow
from .types import Event, Limits

T = TypeVar("T")


class _Subscription(Generic[T]):
    """Enter before submitting work to observe its events without a history buffer.

    A slow consumer receives PiSubscriptionOverflow rather than silently losing
    events. Closing the context unregisters immediately and releases its buffer.
    """

    def __init__(
        self,
        limits: Limits,
        register: Callable[[], None],
        unregister: Callable[[], None],
    ) -> None:
        self._limits = limits
        self._register = register
        self._unregister = unregister
        self._records: deque[tuple[T, int]] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        self._entered = False
        self._closed = False
        self._error: Exception | None = None
        self._reading = False

    async def __aenter__(self) -> Self:
        if self._entered or self._closed:
            raise RuntimeError("Event subscriptions are single-use")
        self._register()
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Unsubscribe and release queued payloads; safe to call repeatedly."""
        self._discard()

    def _discard(self) -> None:
        """Also used by the sync facade after its loop has stopped."""
        self._finish()
        self._records.clear()
        self._bytes = 0
        self._error = None

    def _finish(self, error: Exception | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._error = error
        self._unregister()
        if isinstance(error, PiSubscriptionOverflow):
            # Overflow is loss, not a complete prefix ending at a process failure.
            # Keep it immediate; a healthy terminal queue can still be drained.
            self._records.clear()
            self._bytes = 0
        self._ready.set()

    def _put(self, event: T, size: int) -> Exception | None:
        if self._closed:
            return self._error
        if (
            len(self._records) >= self._limits.event_queue_size
            or self._bytes + size > self._limits.event_queue_bytes
        ):
            error = PiSubscriptionOverflow("Event consumer exceeded its configured buffer limit")
            self._finish(error)
            return error
        self._records.append((event, size))
        self._bytes += size
        self._ready.set()
        return None

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        if not self._entered:
            raise RuntimeError("Enter the event subscription context before iterating")
        if self._reading:
            raise RuntimeError("Only one reader may iterate an event subscription")
        self._reading = True
        try:
            while True:
                event = self._next_nowait()
                if event is not None:
                    return event
                self._ready.clear()
                await self._ready.wait()
        finally:
            self._reading = False

    def _next_nowait(self) -> T | None:
        """Read on the owning loop, or after that loop has completely stopped."""
        if self._records:
            event, size = self._records.popleft()
            self._bytes -= size
            return event
        if self._error is not None:
            raise self._error
        if self._closed:
            raise StopAsyncIteration
        return None


class EventSubscription(_Subscription[Event]):
    """Bounded future events; enter before startup to include startup events."""

    def __init__(
        self,
        limits: Limits,
        register: Callable[[EventSubscription], None],
        unregister: Callable[[EventSubscription], None],
    ) -> None:
        super().__init__(limits, lambda: register(self), lambda: unregister(self))
