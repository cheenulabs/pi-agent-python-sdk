"""One owned conversation run, including settlement and cancellation cleanup."""

from __future__ import annotations

import asyncio
import math
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from ._events import EventSubscription
from .errors import PiBusyError, PiProtocolError, PiRunError, PiRunStartTimeout, PiTimeoutError
from .types import Event, ImageContent, RunResult, UsageSummary

if TYPE_CHECKING:
    from .client import AsyncPiClient, Timeout


def _observed_usage(messages: list[dict[str, Any]]) -> UsageSummary | None:
    assistants = [message for message in messages if message.get("role") == "assistant"]
    if not assistants or not any(isinstance(message.get("usage"), dict) for message in assistants):
        return None

    def total(key: str, *, cost: bool = False) -> float | None:
        values = []
        for message in assistants:
            usage = message.get("usage")
            record = usage.get("cost") if cost and isinstance(usage, dict) else usage
            value = record.get(key) if isinstance(record, dict) else None
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return None
            values.append(value)
        return sum(values)

    return UsageSummary(
        input_tokens=total("input"),
        output_tokens=total("output"),
        cache_read_tokens=total("cacheRead"),
        cache_write_tokens=total("cacheWrite"),
        cache_write_1h_tokens=total("cacheWrite1h"),
        reasoning_tokens=total("reasoning"),
        total_tokens=total("totalTokens"),
        cost=total("total", cost=True),
        assistant_messages=len(assistants),
    )


class RunStream:
    """A single-use owned run. Enter, then iterate or await result() to drain.

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
        if timeout is not None and (
            isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("run timeout must be a positive finite number or None")
        self._client = client
        self._message = message
        self._images = images
        self._timeout = timeout
        self._command_timeout = command_timeout
        self._events = EventSubscription(
            client.limits, lambda subscription: None, lambda subscription: None
        )
        self._started = asyncio.Event()
        self._settled = asyncio.Event()
        self._task: asyncio.Task[RunResult] | None = None
        self._accepted: asyncio.Future[None] | None = None
        self._error: Exception | None = None
        self._messages: list[dict[str, Any]] = []
        self._submitted = False
        self._finishing = False
        self._iterating = False
        self._draining = False
        self._iteration_done = False
        self._begin = 0.0

    async def __aenter__(self) -> Self:
        self._client._check_loop()
        if self._task is not None:
            raise RuntimeError("Run streams are single-use")
        if self._client.busy:
            raise PiBusyError("Another run owns this Pi conversation")
        if not self._client.running:
            raise RuntimeError("Start Pi before opening a run stream")
        self._client._owner = self
        self._accepted = asyncio.get_running_loop().create_future()
        await self._events.__aenter__()
        self._begin = time.monotonic()
        self._task = asyncio.create_task(self._drive(), name="pi-run")
        self._task.add_done_callback(self._consume_task_exception)
        try:
            await asyncio.shield(self._accepted)
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
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except (Exception, asyncio.CancelledError):
                pass
        if self._accepted is not None and self._accepted.done() and not self._accepted.cancelled():
            self._accepted.exception()
        await self._events.aclose()

    def _fail(self, error: Exception) -> None:
        if self._error is not None or self._finishing:
            return
        self._error = error
        self._events._finish(error)
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def _on_event(self, event: Event, size: int) -> None:
        if not self._submitted or self._settled.is_set():
            return
        if event.type == "agent_start":
            self._started.set()
        elif event.type == "agent_settled" and self._started.is_set():
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
            self._messages.append(message)
        error = self._events._put(event, size)
        if error is not None:
            self._fail(error)

    async def _drive(self) -> RunResult:
        assert self._accepted is not None
        failure: BaseException | None = None
        try:
            async with asyncio.timeout(self._timeout):
                state = await self._client.get_state()
                if state["isStreaming"] or state["isCompacting"] or state["pendingMessageCount"]:
                    raise PiBusyError("Pi already has active or queued low-level work")
                fields: dict[str, Any] = {"message": self._message}
                if self._images is not None:
                    fields["images"] = self._images
                self._submitted = True
                await self._client._request(
                    "prompt", fields, timeout=self._command_timeout, owner=self
                )
                self._accepted.set_result(None)
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
            if self._submitted and not self._settled.is_set():
                if isinstance(failure, PiRunStartTimeout):
                    await self._client.aclose()
                else:
                    await self._cleanup()
            if failure is exc:
                raise
            raise failure from exc
        finally:
            if not self._accepted.done():
                if isinstance(failure, asyncio.CancelledError):
                    self._accepted.cancel()
                elif failure is not None:
                    self._accepted.set_exception(failure)
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
            text="\n".join(text_parts),
            messages=list(self._messages),
            stop_reason=last["stopReason"] if last is not None else None,
            session=self._client.session,
            elapsed_seconds=time.monotonic() - self._begin,
            usage=_observed_usage(self._messages),
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
