"""Synchronous access through one persistent event loop per client.

RPC behavior lives in AsyncPiClient. This module only bridges threads and
context managers; it never reads pipes or implements command serialization.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import deque
from collections.abc import Callable, Coroutine, Mapping, Sequence
from types import TracebackType
from typing import Any, Self, TypeVar, cast

from ._observation import ObservationStatus, ProcessObservation, ProcessOutput
from ._runs import RunStream
from ._sync_bridge import _Call as _Call
from ._sync_bridge import _SyncBridge
from ._sync_bridge import _SyncSubscription as _SyncSubscription
from .client import DEFAULT_TIMEOUT, IN_SYNC_UI, AsyncPiClient, Timeout, UIHandler
from .errors import PiSubscriptionOverflow
from .types import (
    AgentMessage,
    BashResult,
    CompactionResult,
    EntriesResult,
    Event,
    ExportHtmlResult,
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
    ThinkingLevelCycleResult,
    TreeResult,
)

T = TypeVar("T")


class PiClient(_SyncBridge[AsyncPiClient]):
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
        super().__init__(
            AsyncPiClient(
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
        )

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

    def _in_callback(self) -> bool:
        return IN_SYNC_UI.get()

    def on_event(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        """Register a short callback on the background loop; return unsubscribe.

        May be called before start(). Blocking client calls from callbacks are
        rejected. Unsubscribe is idempotent and works inside the callback.
        """
        self._ensure_loop()

        async def register() -> Callable[[], None]:
            return self._client.on_event(listener)

        remove = self._call(register)

        async def unregister() -> None:
            remove()

        def unsubscribe() -> None:
            if threading.current_thread() is self._thread:
                remove()
            else:
                self._close_context(unregister)

        return unsubscribe

    def collect_events(self, *, timeout: float | None = 60.0) -> list[Event]:
        """Block while collecting future events through the next settlement.

        Raises PiTimeoutError on timeout, PiSubscriptionOverflow on backlog
        overflow, or PiResultOverflow on retained-history overflow. Terminal
        process/protocol failures propagate. Timeout stops local observation
        without aborting Pi. Use prompt_and_wait() to guarantee registration
        before submitting a prompt.
        """
        self._ensure_loop()

        async def collect() -> list[Event]:
            return await self._client.collect_events(timeout=timeout)

        return self._call(collect)

    def wait_for_idle(self, *, timeout: float | None = 60.0) -> None:
        """Block until the next settlement; this does not query current idle state.

        Raises PiTimeoutError on timeout or PiSubscriptionOverflow on backlog
        overflow. Terminal process/protocol failures propagate. Timeout stops
        local observation without aborting Pi. Use prompt_and_wait() to guarantee
        registration before submitting a prompt.
        """
        self._ensure_loop()

        async def wait() -> None:
            await self._client.wait_for_idle(timeout=timeout)

        self._call(wait)

    def prompt_and_wait(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = 60.0,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> list[Event]:
        """Collect session events until prompt acknowledgement and settlement.

        Failure cancels local waits without aborting Pi. Model stop reasons stay
        in the returned events; no owned run or aggregate result is created.
        """
        return self._call(
            lambda: self._client.prompt_and_wait(
                message, images=images, timeout=timeout, command_timeout=command_timeout
            )
        )

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
    ) -> None:
        """Return None after checked acceptance; handled commands may never start a run.

        Raises PiCommandError on rejection. Use request() for the raw envelope.
        """
        self._call(
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

    def cycle_thinking_level(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> ThinkingLevelCycleResult | None:
        """Return the complete thinking-level result, or None when unavailable."""
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
    ) -> ExportHtmlResult:
        """Return the full export result, including path and unknown metadata."""
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
        """Set the session name; query get_state() explicitly for updated identity."""
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


class SyncEventSubscription(_SyncSubscription[Event]):
    def __init__(self, client: PiClient) -> None:
        super().__init__(client, client._client.events)


class SyncProcessObservation(_SyncSubscription[ProcessOutput]):
    def __init__(self, client: PiClient, *, stderr: bool, stdout: bool, rpc: bool) -> None:
        subscription = client._client.observe(stderr=stderr, stdout=stdout, rpc=rpc)
        super().__init__(client, lambda: subscription)

    def stop(self) -> None:
        """Unsubscribe and preserve buffered output for iteration; keep Pi running.

        Raises:
            RuntimeError: If the observation context has not been entered.
        """
        if self._subscription is None:
            raise RuntimeError("Enter the observation context before stopping")
        self._client._close_context(cast(ProcessObservation, self._subscription).stop)

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
