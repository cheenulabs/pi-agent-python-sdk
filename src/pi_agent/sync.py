"""Synchronous access through one persistent event loop per client.

RPC behavior lives in AsyncPiClient. This module only bridges threads and
context managers; it never reads pipes or implements command serialization.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
from collections import deque
from collections.abc import Callable, Coroutine, Mapping, Sequence
from types import TracebackType
from typing import Any, Generic, Self, TypeVar, cast

from ._events import _Subscription
from ._observation import ObservationStatus, ProcessObservation, ProcessOutput
from ._runs import RunStream
from .client import DEFAULT_TIMEOUT, IN_SYNC_UI, AsyncPiClient, Timeout, UIHandler
from .errors import PiProcessError, PiSubscriptionOverflow
from .types import (
    AcceptanceReceipt,
    AgentMessage,
    BashResult,
    CompactionResult,
    EntriesResult,
    Event,
    ForkMessage,
    ForkResult,
    ImageContent,
    Limits,
    Model,
    ModelCycleResult,
    QueueMode,
    QueueState,
    RunResult,
    SessionChangeResult,
    SessionInfo,
    SessionState,
    SessionStats,
    SlashCommand,
    ThinkingLevel,
    TreeResult,
)

T = TypeVar("T")


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


class PiClient:
    """A blocking facade over AsyncPiClient with the same RPC semantics.

    Construction has no thread or subprocess side effects. Enter a context or
    call start(), and always close(). Calls from multiple threads are routed
    to one loop; conversation ownership remains enforced by the async core.
    Use AsyncPiClient from asynchronous applications.
    """

    def __init__(
        self,
        *,
        executable: str | os.PathLike[str] | Sequence[str] = "pi",
        cwd: str | os.PathLike[str] | None = None,
        provider: str | None = None,
        model: str | None = None,
        env: Mapping[str, str | None] | None = None,
        inherit_env: bool = True,
        session: str | None = None,
        session_dir: str | None = None,
        session_id: str | None = None,
        continue_session: bool = False,
        no_session: bool = False,
        fork_session: str | None = None,
        extra_args: Sequence[str] = (),
        ui_handler: UIHandler | None = None,
        limits: Limits | None = None,
        strict_version: bool = False,
        allow_unknown_version: bool = False,
    ) -> None:
        self._client = AsyncPiClient(
            executable=executable,
            cwd=cwd,
            provider=provider,
            model=model,
            env=env,
            inherit_env=inherit_env,
            session=session,
            session_dir=session_dir,
            session_id=session_id,
            continue_session=continue_session,
            no_session=no_session,
            fork_session=fork_session,
            extra_args=extra_args,
            ui_handler=ui_handler,
            limits=limits,
            strict_version=strict_version,
            allow_unknown_version=allow_unknown_version,
        )
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

    @property
    def limits(self) -> Limits:
        return self._client.limits

    @property
    def running(self) -> bool:
        return self._client.running

    @property
    def busy(self) -> bool:
        return self._client.busy

    @property
    def session(self) -> SessionInfo:
        return self._client.session

    @property
    def pi_version(self) -> str | None:
        return self._client.pi_version

    @property
    def compatibility(self) -> str:
        return self._client.compatibility

    @property
    def stderr_tail(self) -> str:
        return self._client.stderr_tail

    def _check_caller(self) -> None:
        if IN_SYNC_UI.get() or threading.current_thread() is self._thread:
            raise RuntimeError("Blocking PiClient calls are not allowed from UI callbacks")

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

    def request(
        self, command_type: str, *, timeout: Timeout = DEFAULT_TIMEOUT, **fields: Any
    ) -> dict[str, Any]:
        """Return a checked raw response; omission and timeout rules match the async client."""
        return self._call(lambda: self._client.request(command_type, timeout=timeout, **fields))

    def prompt(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        streaming_behavior: str | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> AcceptanceReceipt:
        """Wait for acceptance only; handled commands may never start an agent run."""
        return self._call(
            lambda: self._client.prompt(
                message, images=images, streaming_behavior=streaming_behavior, timeout=timeout
            )
        )

    def steer(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        """Queue input for Pi's next steering opportunity; acknowledgement is not consumption."""
        self._call(lambda: self._client.steer(message, images=images, timeout=timeout))

    def follow_up(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        """Queue input after the current response; acknowledgement is not consumption."""
        self._call(lambda: self._client.follow_up(message, images=images, timeout=timeout))

    def abort(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort current work using Pi semantics, without implicitly clearing queued input."""
        self._call(lambda: self._client.abort(timeout=timeout))

    def clear_queue(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> QueueState:
        """Clear queued input and return the removed steering and follow-up text."""
        return self._call(lambda: self._client.clear_queue(timeout=timeout))

    def new_session(
        self, *, parent_session: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
        """Start a new session; inspect cancelled for an extension veto."""
        return self._call(
            lambda: self._client.new_session(parent_session=parent_session, timeout=timeout)
        )

    def get_state(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionState:
        """Read authoritative Pi state and refresh the cached session identity."""
        return self._call(lambda: self._client.get_state(timeout=timeout))

    def set_model(
        self, provider: str, model_id: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> Model:
        """Select a provider/model and return its full metadata."""
        return self._call(lambda: self._client.set_model(provider, model_id, timeout=timeout))

    def cycle_model(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ModelCycleResult | None:
        """Cycle models and return model, thinking level, and scope, or None."""
        return self._call(lambda: self._client.cycle_model(timeout=timeout))

    def get_available_models(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[Model]:
        """List the models Pi makes available with their provider metadata."""
        return self._call(lambda: self._client.get_available_models(timeout=timeout))

    def set_thinking_level(
        self, level: ThinkingLevel, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Request a thinking level for the current model."""
        self._call(lambda: self._client.set_thinking_level(level, timeout=timeout))

    def cycle_thinking_level(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ThinkingLevel | None:
        """Cycle the current thinking level, or return None when unavailable."""
        return self._call(lambda: self._client.cycle_thinking_level(timeout=timeout))

    def get_available_thinking_levels(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> list[ThinkingLevel]:
        """List thinking levels available for the current model."""
        return self._call(lambda: self._client.get_available_thinking_levels(timeout=timeout))

    def set_steering_mode(self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Choose all queued steering messages or one at a time."""
        self._call(lambda: self._client.set_steering_mode(mode, timeout=timeout))

    def set_follow_up_mode(self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Choose all queued follow-up messages or one at a time."""
        self._call(lambda: self._client.set_follow_up_mode(mode, timeout=timeout))

    def compact(
        self, *, custom_instructions: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> CompactionResult:
        """Compact the conversation and return Pi's summary and token information."""
        return self._call(
            lambda: self._client.compact(custom_instructions=custom_instructions, timeout=timeout)
        )

    def set_auto_compaction(self, enabled: bool, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Enable or disable Pi's automatic context compaction."""
        self._call(lambda: self._client.set_auto_compaction(enabled, timeout=timeout))

    def set_auto_retry(self, enabled: bool, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Enable or disable Pi's automatic retry policy."""
        self._call(lambda: self._client.set_auto_retry(enabled, timeout=timeout))

    def abort_retry(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort Pi's active retry sequence."""
        self._call(lambda: self._client.abort_retry(timeout=timeout))

    def bash(
        self,
        command: str,
        *,
        exclude_from_context: bool | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> BashResult:
        """Run Pi's bash command; events() exposes output deltas while it executes."""
        return self._call(
            lambda: self._client.bash(
                command, exclude_from_context=exclude_from_context, timeout=timeout
            )
        )

    def abort_bash(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort Pi's active bash execution."""
        self._call(lambda: self._client.abort_bash(timeout=timeout))

    def get_session_stats(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionStats:
        """Return Pi's current session message counts, token totals, and cost."""
        return self._call(lambda: self._client.get_session_stats(timeout=timeout))

    def export_html(
        self, *, output_path: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> str:
        """Export the current session and return the path written by Pi."""
        return self._call(
            lambda: self._client.export_html(output_path=output_path, timeout=timeout)
        )

    def switch_session(
        self, session_path: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
        """Switch to a session path; inspect cancelled for an extension veto."""
        return self._call(lambda: self._client.switch_session(session_path, timeout=timeout))

    def fork(self, entry_id: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ForkResult:
        """Fork at an eligible entry; a veto can omit the returned editable text."""
        return self._call(lambda: self._client.fork(entry_id, timeout=timeout))

    def clone(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionChangeResult:
        """Clone the current session; inspect cancelled for an extension veto."""
        return self._call(lambda: self._client.clone(timeout=timeout))

    def get_fork_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[ForkMessage]:
        """List eligible message entry IDs and text for choosing a fork point."""
        return self._call(lambda: self._client.get_fork_messages(timeout=timeout))

    def get_entries(
        self, *, since: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> EntriesResult:
        """Return saved entries after an optional entry ID and the current leaf ID."""
        return self._call(lambda: self._client.get_entries(since=since, timeout=timeout))

    def get_tree(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> TreeResult:
        """Return the recursive session tree and nullable selected leaf ID."""
        return self._call(lambda: self._client.get_tree(timeout=timeout))

    def get_last_assistant_text(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> str | None:
        """Query session history for usable assistant text, or None when absent."""
        return self._call(lambda: self._client.get_last_assistant_text(timeout=timeout))

    def set_session_name(self, name: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Set the session name and refresh cached identity from Pi."""
        self._call(lambda: self._client.set_session_name(name, timeout=timeout))

    def get_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[AgentMessage]:
        """Return Pi's current conversation messages."""
        return self._call(lambda: self._client.get_messages(timeout=timeout))

    def get_commands(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[SlashCommand]:
        """List extension, prompt-template, and skill commands with source information."""
        return self._call(lambda: self._client.get_commands(timeout=timeout))

    def observe(
        self, *, stderr: bool = True, stdout: bool = False, rpc: bool = False
    ) -> SyncProcessObservation:
        """Observe selected process output; enter before start for lifetime coverage.

        Raises ValueError if no source is selected. Slow consumers raise
        PiSubscriptionOverflow. Close the client and drain this iterator before
        checking status.complete and status.error; terminal process failures are
        reported through status.error after output drains.
        """
        return SyncProcessObservation(self, stderr=stderr, stdout=stdout, rpc=rpc)

    def events(self) -> SyncEventSubscription:
        """Enter before submitting work, then iterate future events on the calling thread."""
        return SyncEventSubscription(self)

    def stream(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = None,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> SyncRunStream:
        """Enter a context and iterate events; leaving early aborts owned work."""
        return SyncRunStream(self, message, images, timeout, command_timeout)

    def run(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = None,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Wait through retries and queued continuations until agent_settled."""
        return self._call(
            lambda: self._client.run(
                message, images=images, timeout=timeout, command_timeout=command_timeout
            )
        )


class _SyncSubscription(Generic[T]):
    """A blocking context and iterator over a bounded async subscription."""

    def __init__(self, client: PiClient, factory: Callable[[], _Subscription[T]]) -> None:
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


class SyncEventSubscription(_SyncSubscription[Event]):
    def __init__(self, client: PiClient) -> None:
        super().__init__(client, client._client.events)


class SyncProcessObservation(_SyncSubscription[ProcessOutput]):
    def __init__(self, client: PiClient, *, stderr: bool, stdout: bool, rpc: bool) -> None:
        subscription = client._client.observe(stderr=stderr, stdout=stdout, rpc=rpc)
        super().__init__(client, lambda: subscription)

    @property
    def status(self) -> ObservationStatus:
        if self._subscription is None:
            return ObservationStatus()
        return cast(ProcessObservation, self._subscription).status


class SyncRunStream:
    """An owned run; iterate once, then result(), or use result() alone to drain."""

    def __init__(
        self,
        client: PiClient,
        message: str,
        images: list[ImageContent] | None,
        timeout: float | None,
        command_timeout: Timeout,
    ) -> None:
        self._client = client
        self._message = message
        self._images = images
        self._timeout = timeout
        self._command_timeout = command_timeout
        self._stream: RunStream | None = None
        self._entered = False
        self._closed = False
        self._batch: deque[Event] = deque()
        self._reading = threading.RLock()

    def __enter__(self) -> Self:
        async def enter() -> None:
            if self._entered or self._closed:
                raise RuntimeError("Run streams are single-use")
            self._entered = True
            self._stream = self._client._client.stream(
                self._message,
                images=self._images,
                timeout=self._timeout,
                command_timeout=self._command_timeout,
            )
            await self._stream.__aenter__()

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
        # Iterator wrappers may call iter() repeatedly before requesting an item.
        # The async next/result methods enforce actual competing consumption.
        return self

    def _call_owned(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        async def invoke() -> T:
            try:
                return await operation()
            except asyncio.CancelledError:
                if self._stream is not None:
                    await self._stream.aclose()
                raise

        try:
            return self._client._call(invoke)
        except KeyboardInterrupt:
            # Cancellation before invoke() starts cannot run its exception handler.
            self.close()
            raise

    def __next__(self) -> Event:
        self._client._check_caller()
        if not self._reading.acquire(blocking=False):
            raise RuntimeError("Only one reader may iterate an event subscription")

        async def next_events() -> list[Event]:
            if self._stream is None:
                raise RuntimeError("Enter the stream context before iterating")
            return await self._stream._next_batch()

        try:
            error = self._stream._events._error if self._stream is not None else None
            if isinstance(error, PiSubscriptionOverflow):
                self._batch.clear()
                raise error
            if not self._batch:
                self._batch.extend(self._call_owned(next_events))
            return self._batch.popleft()
        except StopAsyncIteration:
            raise StopIteration from None
        finally:
            self._reading.release()

    def result(self) -> RunResult:
        async def result() -> RunResult:
            if self._stream is None:
                raise RuntimeError("Enter the stream context before requesting its result")
            return await self._stream.result()

        return self._call_owned(result)

    def close(self) -> None:
        self._closed = True
        if self._stream is not None:
            self._client._close_context(self._stream.aclose)
        with self._reading:
            self._batch.clear()
