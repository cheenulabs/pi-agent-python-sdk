"""One owned conversation run, including settlement and cancellation cleanup."""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from ._events import EventSubscription
from ._usage import UsageAccumulator
from .errors import (
    PiBusyError,
    PiCommandError,
    PiProtocolError,
    PiResultOverflow,
    PiRunError,
    PiRunOwnershipError,
    PiRunStartTimeout,
    PiTimeoutError,
)
from .types import Event, ImageContent, RunResult, _validate_timeout

if TYPE_CHECKING:
    from .client import AsyncPiClient, Timeout


class RunStream:
    """A single-use owned run. Enter on acceptance or start, then consume events.

    Breaking iteration must be followed by leaving the context so queued work
    is cleared and Pi is aborted. An accepted command without a start event
    has an uncertain disposition; its start deadline closes Pi.
    """

    def __init__(
        self,
        client: AsyncPiClient,
        message: str,
        *,
        images: list[ImageContent] | None,
        timeout: float | None,
        command_timeout: Timeout,
    ) -> None:
        if timeout is not None:
            _validate_timeout(timeout, "run timeout")
        self._client = client
        self._message = message
        self._images = images
        self._timeout = timeout
        self._command_timeout = command_timeout
        self._events = EventSubscription(
            client.limits, lambda subscription: None, lambda subscription: None
        )
        self._retain_events = True
        self._started = asyncio.Event()
        self._settled = asyncio.Event()
        self._task: asyncio.Task[RunResult] | None = None
        self._ready: asyncio.Future[None] | None = None
        self._accepted = False
        self._error: Exception | None = None
        self._messages: list[dict[str, Any]] = []
        self._message_bytes = 0
        self._usage = UsageAccumulator()
        self._submitted = False
        self._finishing = False
        self._closed = False
        self._iterating = False
        self._draining = False
        self._iteration_done = False
        self._begin = 0.0
        self._end = 0.0

    async def __aenter__(self) -> Self:
        self._client._check_loop()
        if self._task is not None or self._closed:
            raise RuntimeError("Run streams are single-use")
        if self._client.busy:
            raise PiBusyError("Another run owns this Pi conversation")
        if not self._client.running:
            raise RuntimeError("Start Pi before opening a run stream")
        if self._client._unowned_submission:
            raise PiRunOwnershipError(
                "This client submitted low-level conversation work; use a fresh client for "
                "run()/stream() because delayed session events cannot be attributed safely"
            )
        self._client._owner = self
        self._ready = asyncio.get_running_loop().create_future()
        await self._events.__aenter__()
        self._task = asyncio.create_task(self._drive(), name="pi-run")
        self._task.add_done_callback(self._consume_task_exception)
        try:
            await self._ready
            if self._error is not None:
                raise self._error
        except BaseException:
            await self.aclose()
            raise
        return self

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[RunResult]) -> None:
        if not task.cancelled():
            task.exception()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Finish cancellation cleanup before releasing the owned conversation."""
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except (Exception, asyncio.CancelledError):
                pass
        if self._ready is not None and self._ready.done() and not self._ready.cancelled():
            self._ready.exception()
        await self._events.aclose()

    def _fail(self, error: Exception) -> None:
        if self._error is not None or self._finishing:
            return
        self._error = error
        self._events._finish(error)
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def _on_event(self, event: Event, size: int) -> None:
        if not self._submitted or self._settled.is_set() or self._error is not None:
            return
        if event.type == "agent_start":
            self._started.set()
            # Extensions may wait for the entire run before acknowledging the
            # prompt. Make consumption possible without declaring acceptance.
            if self._ready is not None and not self._ready.done():
                self._ready.set_result(None)
        elif event.type == "agent_settled" and self._started.is_set():
            self._end = time.monotonic()
            self._settled.set()
        elif event.type == "message_end" and self._started.is_set():
            message = event.raw.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                self._fail(PiProtocolError("message_end requires a message with a role"))
                return
            if message.get("role") == "assistant":
                if not isinstance(message.get("content"), list) or not isinstance(
                    message.get("stopReason"), str
                ):
                    self._fail(
                        PiProtocolError("Final assistant message requires content and stopReason")
                    )
                    return
            if (
                len(self._messages) >= self._client.limits.result_message_count
                or self._message_bytes + size > self._client.limits.result_message_bytes
            ):
                self._fail(PiResultOverflow("Run exceeded its retained message count/byte limit"))
                return
            self._message_bytes += size
            self._messages.append(message)
            self._usage.add(message)
        if self._retain_events:
            error = self._events._put(event, size)
            if error is not None:
                self._fail(error)

    def _mark_submitted(self) -> None:
        self._submitted = True
        self._begin = time.monotonic()

    async def _drive(self) -> RunResult:
        assert self._ready is not None
        failure: BaseException | None = None
        try:
            async with asyncio.timeout(self._timeout):
                state = await self._client.get_state()
                if state["isStreaming"] or state["isCompacting"] or state["pendingMessageCount"]:
                    raise PiBusyError("Pi already has active or queued low-level work")
                fields: dict[str, Any] = {"message": self._message}
                if self._images is not None:
                    fields["images"] = self._images
                await self._client._request(
                    "prompt", fields, timeout=self._command_timeout, owner=self
                )
                self._accepted = True
                if not self._ready.done():
                    self._ready.set_result(None)
                try:
                    async with asyncio.timeout(self._client.limits.run_start_timeout):
                        await self._started.wait()
                except TimeoutError as exc:
                    raise PiRunStartTimeout(
                        "Prompt accepted but no run was observed; "
                        "Pi is closed to prevent delayed work",
                        command="prompt",
                        uncertain=True,
                    ) from exc
                await self._settled.wait()
                if self._error is not None:
                    raise self._error
                # Extensions can switch sessions internally; do not reuse startup identity.
                await self._client.get_state()
                result = self._result()
                if result.stop_reason in {"error", "aborted"}:
                    raise PiRunError(f"Pi run ended with {result.stop_reason}", result)
                return result
        except BaseException as exc:
            self._finishing = True
            failure = exc
            if isinstance(exc, asyncio.CancelledError) and self._error is not None:
                failure = self._error
            elif isinstance(exc, TimeoutError) and not isinstance(exc, PiTimeoutError):
                failure = PiTimeoutError(
                    "Pi run deadline elapsed", command="prompt", uncertain=self._submitted
                )
            if self._client._ui_error is not None and failure is self._client._ui_error:
                # The owner now reports this failure. Do not report it again as
                # a failure of an otherwise successful cleanup command.
                self._client._ui_error = None
            if (
                self._submitted
                and (not isinstance(failure, PiCommandError) or self._started.is_set())
                and (not self._settled.is_set() or not self._accepted)
            ):
                # abort() cannot cancel an extension's pending input/UI preflight.
                # Keep delayed work from escaping a failed owned operation.
                if not self._accepted or not self._started.is_set():
                    await self._client.aclose()
                else:
                    await self._cleanup()
            if failure is exc:
                raise
            if self._error is not None and failure is self._error:
                # Cancellation only woke the driver; retain the recorded
                # error's original cause (for example the UI callback error).
                raise failure from failure.__cause__
            raise failure from exc
        finally:
            if not self._ready.done():
                if isinstance(failure, asyncio.CancelledError):
                    self._ready.cancel()
                elif failure is not None:
                    self._ready.set_exception(failure)
            # Final model errors are delivered by result(), after their events are consumed.
            event_error = (
                failure
                if isinstance(failure, Exception) and not isinstance(failure, PiRunError)
                else None
            )
            self._events._finish(event_error)
            if self._client._owner is self:
                self._client._owner = None

    async def _cleanup(self) -> None:
        async def stop() -> None:
            if not self._client.running:
                await self._client.aclose()
                return
            try:
                async with asyncio.timeout(self._client.limits.cleanup_timeout):
                    await self._client._request("clear_queue", owner=self)
                    await self._client._request("abort", owner=self)
            except Exception:
                await self._client.aclose()

        # Shield cleanup from the caller's cancellation, retaining ownership until it completes.
        task = asyncio.create_task(stop(), name="pi-run-cleanup")
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task

    def _result(self) -> RunResult:
        assistants = [message for message in self._messages if message["role"] == "assistant"]
        last = assistants[-1] if assistants else None
        content = last["content"] if last is not None else []
        text_parts = []
        for block in content:
            if not isinstance(block, dict):
                raise PiProtocolError("Assistant content blocks must be objects")
            if block.get("type") == "text":
                if not isinstance(block.get("text"), str):
                    raise PiProtocolError("Assistant text blocks require string text")
                text_parts.append(block["text"])
        return RunResult(
            text="".join(text_parts),
            messages=list(self._messages),
            stop_reason=last["stopReason"] if last is not None else None,
            session=self._client.session,
            elapsed_seconds=max(0.0, self._end - self._begin),
            usage=self._usage.snapshot(),
        )

    def __aiter__(self) -> Self:
        if self._draining:
            raise PiBusyError("Cannot iterate while result() drains the stream")
        if self._iterating:
            raise PiBusyError("A stream permits one event iterator")
        self._iterating = True
        return self

    async def __anext__(self) -> Event:
        if self._draining:
            raise PiBusyError("Cannot iterate while result() drains the stream")
        self._iterating = True
        try:
            return await self._events.__anext__()
        except StopAsyncIteration:
            self._iteration_done = True
            raise

    async def _next_batch(self) -> list[Event]:
        if self._draining:
            raise PiBusyError("Cannot iterate while result() drains the stream")
        self._iterating = True
        try:
            return await self._events._next_batch()
        except StopAsyncIteration:
            self._iteration_done = True
            raise

    async def result(self) -> RunResult:
        """Drain without retaining events, or return the result after iteration ends."""
        if self._task is None:
            raise RuntimeError("Enter the stream context before awaiting its result")
        if self._draining or (self._iterating and not self._iteration_done):
            raise PiBusyError("Finish iteration before calling result()")
        self._draining = True
        try:
            if not self._iteration_done:
                async for _ in self._events:
                    pass
                self._iteration_done = True
            return await asyncio.shield(self._task)
        finally:
            self._draining = False
