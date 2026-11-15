"""Shared blocking lifecycle and subscriptions over one persistent loop thread."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections import deque
from collections.abc import Callable, Coroutine
from types import TracebackType
from typing import Any, Generic, Protocol, Self, TypeVar

from ._events import _Subscription
from .errors import PiProcessError, PiSubscriptionOverflow


class _AsyncLifecycle(Protocol):
    async def start(self) -> None: ...
    async def aclose(self) -> None: ...


T = TypeVar("T")
C = TypeVar("C", bound=_AsyncLifecycle)


class _Call(Generic[T]):
    """Track task completion separately from a caller abandoning its result."""

    def __init__(self, factory: Callable[[], Coroutine[Any, Any, T]]) -> None:
        self.factory = factory
        self.result: concurrent.futures.Future[T] = concurrent.futures.Future()
        self.finished = threading.Event()
        self.task: asyncio.Task[T] | None = None
        self.cancelled = False

    def start(self) -> None:
        async def invoke() -> T:
            return await self.factory()

        self.task = asyncio.create_task(invoke(), name="pi-sync-call")
        self.task.add_done_callback(self._done)
        if self.cancelled:
            self.task.cancel()

    def cancel(self) -> None:
        self.cancelled = True
        if self.task is not None:
            self.task.cancel()

    def _done(self, task: asyncio.Task[T]) -> None:
        try:
            self.result.set_result(task.result())
        except BaseException as exc:
            self.result.set_exception(exc)
        finally:
            self.finished.set()


class _SyncBridge(Generic[C]):
    """Bridge an async start/aclose lifecycle without knowing its protocol."""

    def __init__(self, client: C) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._closed_event = threading.Event()
        self._thread_done = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_error: BaseException | None = None
        self._closing = False
        self._closed = False
        self._started = False

    def _in_callback(self) -> bool:
        return False

    def _check_caller(self) -> None:
        if self._in_callback() or threading.current_thread() is self._thread:
            raise RuntimeError("Blocking PiClient calls are not allowed from client callbacks")

    def _loop_main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        except BaseException as exc:
            self._loop_error = exc
            if loop is not None:
                loop.close()
            # The starting thread must wake even when no loop could be created.
            self._ready.set()
            self._thread_done.set()
            return
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:

            async def finish() -> None:
                remaining = [
                    task for task in asyncio.all_tasks() if task is not asyncio.current_task()
                ]
                for task in remaining:
                    task.cancel()
                if remaining:
                    await asyncio.gather(*remaining, return_exceptions=True)
                await loop.shutdown_asyncgens()

            try:
                loop.run_until_complete(finish())
            finally:
                # A user callback may be blocked in a worker thread. Python cannot
                # forcibly stop it; closing the loop does not wait for such callbacks.
                loop.close()
                self._thread_done.set()

    def _call(
        self,
        factory: Callable[[], Coroutine[Any, Any, T]],
        *,
        closing: bool = False,
        cancel_on_interrupt: bool = True,
    ) -> T:
        self._check_caller()
        call = _Call(factory)
        with self._lock:
            loop = self._loop
            if (
                loop is None
                or self._thread_done.is_set()
                or self._closed
                or (self._closing and not closing)
            ):
                raise PiProcessError("Pi is not running; use the client context or start() first")
            loop.call_soon_threadsafe(call.start)
        try:
            return call.result.result()
        except KeyboardInterrupt:
            if cancel_on_interrupt:
                loop.call_soon_threadsafe(call.cancel)
            # Future.cancel() marks a bridge cancelled before async finally blocks
            # finish. Only the task's done callback proves cleanup has completed.
            while not call.finished.is_set():
                try:
                    call.finished.wait()
                except KeyboardInterrupt:
                    continue
            raise

    def _ensure_loop(self) -> None:
        self._check_caller()
        with self._lock:
            if self._closed or self._closing:
                raise PiProcessError("Client is closed")
            if self._thread is None:
                thread = threading.Thread(
                    target=self._loop_main, name="pi-client-loop", daemon=True
                )
                try:
                    thread.start()
                except BaseException:
                    self._closed = True
                    self._closed_event.set()
                    raise
                self._thread = thread
        self._ready.wait()
        if self._loop_error is not None:
            self.close()
            raise PiProcessError("Could not initialize the Pi event loop") from self._loop_error

    def start(self) -> None:
        """Launch Pi and wait for readiness, reusing any pre-start observer loop."""
        self._check_caller()
        with self._lock:
            if self._started or self._closed or self._closing:
                raise PiProcessError("Clients are single-use; create a new client to restart Pi")
            self._started = True
        try:
            self._ensure_loop()
            self._call(self._client.start)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Reap Pi, finish outstanding calls, and stop and join the background loop."""
        self._check_caller()
        with self._lock:
            if self._closed:
                return
            other_closer = self._closing
            self._closing = True
            thread = self._thread
        if other_closer:
            self._closed_event.wait()
            return
        try:
            if thread is not None:
                self._ready.wait()
                try:
                    # Interrupting shutdown must not cancel process reaping.
                    if self._loop is not None and not self._thread_done.is_set():
                        self._call(self._client.aclose, closing=True, cancel_on_interrupt=False)
                finally:
                    if self._loop is not None and not self._loop.is_closed():
                        self._loop.call_soon_threadsafe(self._loop.stop)
                    interrupted = False
                    while not self._thread_done.is_set():
                        try:
                            self._thread_done.wait()
                        except KeyboardInterrupt:
                            interrupted = True
                    thread.join()
                    if interrupted:
                        raise KeyboardInterrupt
        finally:
            with self._lock:
                self._closed = True
                self._closed_event.set()

    def _close_context(self, close: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Close a nested context, or join client shutdown already doing its cleanup."""
        try:
            self._call(close, cancel_on_interrupt=False)
        except PiProcessError:
            with self._lock:
                shutting_down = self._closing or self._closed
            if not shutting_down:
                raise
            self.close()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _SyncSubscription(Generic[T]):
    """A blocking context and iterator over a bounded async subscription."""

    def __init__(self, client: _SyncBridge[Any], factory: Callable[[], _Subscription[T]]) -> None:
        self._client = client
        self._factory = factory
        self._subscription: _Subscription[T] | None = None
        self._entered = False
        self._closed = False
        self._batch: deque[T] = deque()
        self._reading = threading.RLock()

    def __enter__(self) -> Self:
        async def enter() -> None:
            if self._entered or self._closed:
                raise RuntimeError("Event subscriptions are single-use")
            self._entered = True
            self._subscription = self._factory()
            await self._subscription.__aenter__()

        self._client._ensure_loop()
        self._client._call(enter)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        self._client._check_caller()
        if not self._reading.acquire(blocking=False):
            raise RuntimeError("Only one reader may iterate an event subscription")
        try:
            error = self._subscription._error if self._subscription is not None else None
            if isinstance(error, PiSubscriptionOverflow):
                self._batch.clear()
                raise error
            if not self._batch:
                self._batch.extend(self._next_batch())
            return self._batch.popleft()
        finally:
            self._reading.release()

    def _next_batch(self) -> list[T]:
        async def next_event() -> list[T]:
            if self._subscription is None:
                raise RuntimeError("Enter the event subscription context before iterating")
            return await self._subscription._next_batch()

        try:
            if self._subscription is None:
                raise RuntimeError("Enter the event subscription context before iterating")
            with self._client._lock:
                stopped = self._client._closed or self._client._closing
            if stopped:
                self._client.close()
                with self._client._lock:
                    event = self._subscription._next_nowait()
                    assert event is not None
                    return [event]
            try:
                return self._client._call(next_event)
            except PiProcessError:
                # close() can win between the state check and scheduling the call.
                with self._client._lock:
                    stopping = self._client._closing or self._client._closed
                if not stopping:
                    raise
                self._client.close()
                with self._client._lock:
                    event = self._subscription._next_nowait()
                    assert event is not None
                    return [event]
        except StopAsyncIteration:
            raise StopIteration from None

    def close(self) -> None:
        self._closed = True
        if self._subscription is not None:
            self._client._close_context(self._subscription.aclose)
        with self._reading:
            if self._subscription is not None:
                self._subscription._discard(buffered=bool(self._batch))
            self._batch.clear()
