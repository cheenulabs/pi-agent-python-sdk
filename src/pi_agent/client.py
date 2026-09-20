"""Async lifecycle, explicit RPC methods, and extension interaction."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

from ._collections import deadline, start_collection
from ._events import EventSubscription
from ._launch import check_version, executable_argv, validate_extra_args
from ._observation import ObservationStatus, OutputSource, ProcessObservation, ProcessOutput
from ._transport import Transport
from .errors import (
    PiBusyError,
    PiProcessError,
    PiProtocolError,
    PiSubscriptionOverflow,
    PiTimeoutError,
    PiUIHandlerError,
)
from .types import (
    AgentMessage,
    BashResult,
    CompactionResult,
    EntriesResult,
    Event,
    ExportHtmlResult,
    ExtensionUIRequest,
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
    _validate_timeout,
)

if TYPE_CHECKING:
    from ._runs import RunStream

UIValue = str | bool | None
UIHandler = Callable[[ExtensionUIRequest], UIValue | Awaitable[UIValue]]
IN_SYNC_UI: contextvars.ContextVar[bool] = contextvars.ContextVar("pi_sync_ui", default=False)


class _DefaultTimeout(Enum):
    DEFAULT = "configured command timeout"


DEFAULT_TIMEOUT = _DefaultTimeout.DEFAULT
Timeout = float | None | _DefaultTimeout
_LONG_COMMANDS = {
    "bash",
    "compact",
    "new_session",
    "switch_session",
    "fork",
    "clone",
    "export_html",
}
_SESSION_COMMANDS = {"new_session", "switch_session", "fork", "clone", "set_session_name"}
_DURING_RUN = {
    "steer",
    "follow_up",
    "abort",
    "clear_queue",
    "abort_retry",
    "abort_bash",
    "get_state",
    "get_available_models",
    "get_available_thinking_levels",
    "get_session_stats",
    "get_fork_messages",
    "get_entries",
    "get_tree",
    "get_last_assistant_text",
    "get_messages",
    "get_commands",
}
_DIALOGS = {"select", "confirm", "input", "editor"}


class AsyncPiClient:
    """Own a Pi RPC process while preserving its normal configuration.

    Use ``async with`` or call start()/aclose(). One high-level run may own the
    conversation; steering, follow-ups, abort and reads remain available.
    ``env`` overrides inherited variables; None removes one. Set inherit_env
    false for an entirely explicit child environment. No network checks or
    credential reads are performed by the client.
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
        if sum((session is not None, continue_session, fork_session is not None)) > 1:
            raise ValueError("Choose only one of session, continue_session, or fork_session")
        if no_session and (session or continue_session or fork_session or session_dir):
            raise ValueError("no_session conflicts with persisted session options")
        if session_id and (session or continue_session):
            raise ValueError("session_id conflicts with opening an existing session")
        validate_extra_args(extra_args)
        self._executable = executable
        self._cwd = os.fspath(cwd) if cwd is not None else None
        self._env_overrides = dict(env or {})
        self._inherit_env = inherit_env
        self._args = ["--mode", "rpc"]
        for flag, value in (
            ("--provider", provider),
            ("--model", model),
            ("--session", session),
            ("--session-dir", session_dir),
            ("--session-id", session_id),
            ("--fork", fork_session),
        ):
            if value is not None:
                self._args.extend((flag, value))
        if no_session:
            self._args.append("--no-session")
        if continue_session:
            self._args.append("--continue")
        self._args.extend(extra_args)
        self.limits = limits or Limits()
        self._ui_handler = ui_handler
        self._strict_version = strict_version
        self._allow_unknown_version = allow_unknown_version
        self._transport: Transport | None = None
        self._subscriptions: set[EventSubscription] = set()
        self._listeners: dict[object, Callable[[Event], None]] = {}
        self._observations: set[ProcessObservation] = set()
        self._process_started_at_ns: int | None = None
        self._ui_tasks: set[asyncio.Task[None]] = set()
        self._ui_bytes = 0
        self._ui_error: PiUIHandlerError | None = None
        self._owner: RunStream | None = None
        self._unowned_submission = False
        self._session = SessionInfo()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._terminal_error: Exception | None = None
        self._close_error: Exception | None = None
        self._starting = False
        self._startup_task: asyncio.Task[Any] | None = None
        self._startup_done = asyncio.Event()
        self._close_task: asyncio.Task[None] | None = None
        self._close_initiator: asyncio.Task[Any] | None = None
        self.pi_version: str | None = None
        self.compatibility: str = "unchecked"

    @property
    def running(self) -> bool:
        return self._transport is not None and self._transport.running and not self._starting

    @property
    def busy(self) -> bool:
        """Whether a run()/stream() owns the conversation, not Pi's global idle state."""
        return self._owner is not None

    @property
    def session(self) -> SessionInfo:
        return self._session

    @property
    def stderr_tail(self) -> str:
        """Explicit diagnostic access; retention is disabled by default."""
        return self._transport.stderr_tail if self._transport is not None else ""

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise RuntimeError("Use the client only from its owning event loop")

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def start(self) -> None:
        """Check the selected version and wait for a real get_state response."""
        if self._closed or self._starting or self._transport is not None:
            raise PiProcessError("Clients are single-use; create a new client to restart Pi")
        self._check_loop()
        self._starting = True
        self._startup_task = asyncio.current_task()
        self._startup_done.clear()
        child_env = dict(os.environ) if self._inherit_env else {}
        for name, value in self._env_overrides.items():
            if value is None:
                child_env.pop(name, None)
            else:
                child_env[name] = value
        try:
            async with asyncio.timeout(self.limits.startup_timeout):
                argv = executable_argv(self._executable, child_env)
                self.pi_version, self.compatibility = await check_version(
                    argv,
                    cwd=self._cwd,
                    env=child_env,
                    timeout=self.limits.startup_timeout,
                    allow_unknown=self._allow_unknown_version,
                    strict=self._strict_version,
                )
                if self._closed:
                    raise PiProcessError("Client was closed during startup")
                self._transport = Transport(
                    limits=self.limits,
                    on_event=self._on_event,
                    on_failure=self._on_failure,
                    on_output=self._on_output,
                    on_output_end=self._on_output_end,
                )
                self._process_started_at_ns = time.time_ns()
                for observer in self._observations:
                    observer._status = replace(
                        observer.status, started_at_ns=self._process_started_at_ns
                    )
                await self._transport.start([*argv, *self._args], cwd=self._cwd, env=child_env)
                response = await self._transport.request(
                    "get_state", timeout=self.limits.startup_timeout
                )
                self._update_session(self._data(response))
        except TimeoutError as exc:
            error = PiTimeoutError("Pi startup timed out", uncertain=False)
            self._on_failure(error)
            if not self._closed:
                await self.aclose()
            raise error from exc
        except BaseException as exc:
            self._on_failure(
                exc if isinstance(exc, Exception) else PiProcessError("Pi startup was cancelled")
            )
            if not self._closed:
                await self.aclose()
            raise
        finally:
            self._starting = False
            self._startup_task = None
            self._startup_done.set()

    async def aclose(self) -> None:
        """Wake all operations and reap the child; repeated calls are safe."""
        self._check_loop()
        if self._close_task is None:
            self._close_error = self._terminal_error
            self._closed = True
            self._close_initiator = asyncio.current_task()
            self._close_task = asyncio.create_task(self._finish_close(), name="pi-client-close")
        await asyncio.shield(self._close_task)

    async def _finish_close(self) -> None:
        startup = self._startup_task
        if startup is not None and startup is not self._close_initiator and not startup.done():
            startup.cancel()
            # start() may be part of a larger application task whose finally
            # also closes us. Wait for startup cleanup, not that whole task.
            await self._startup_done.wait()
        if self._transport is not None:
            await self._transport.aclose()
        if self._transport is None:
            self._on_output_end(False, False, True, self._terminal_error)
        self._on_failure(PiProcessError("Client is closed"))
        tasks = tuple(task for task in self._ui_tasks if task is not self._close_initiator)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._close_initiator = None

    def on_event(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        """Register a short synchronous callback on this loop; return unsubscribe.

        Registration may precede start(). Unsubscribe is idempotent and may be
        called during delivery; removal before a listener's turn skips it.
        Listener exceptions go to the loop exception handler, not other listeners.
        """
        self._check_loop()
        if self._closed or self._terminal_error is not None:
            raise PiProcessError("Cannot listen to a closed or failed client")
        if (
            not callable(listener)
            or inspect.iscoroutinefunction(listener)
            or inspect.iscoroutinefunction(cast(Any, listener).__call__)
        ):
            raise TypeError("Event listeners must be synchronous callables")
        key = object()
        self._listeners[key] = listener

        def unsubscribe() -> None:
            self._check_loop()
            self._listeners.pop(key, None)

        return unsubscribe

    def collect_events(self, *, timeout: float | None = 60.0) -> asyncio.Task[list[Event]]:
        """Register immediately; return a cancellable task collecting through settlement.

        Events are session-wide, with separate collection count/byte limits.
        Awaiting raises PiTimeoutError on timeout, PiSubscriptionOverflow on
        backlog overflow, or PiResultOverflow on retained-history overflow.
        Terminal process/protocol failures propagate. Timeout or cancellation
        stops local observation without aborting Pi.
        """
        self._check_loop()
        return cast(
            "asyncio.Task[list[Event]]",
            start_collection(self.events(), self.limits, timeout=timeout, retain=True),
        )

    def wait_for_idle(self, *, timeout: float | None = 60.0) -> asyncio.Task[None]:
        """Register immediately for the next settlement, without retaining events.

        This does not query whether Pi is idle already; use get_state() for that.
        Awaiting raises PiTimeoutError on timeout or PiSubscriptionOverflow on
        backlog overflow. Terminal process/protocol failures propagate. Timeout
        or cancellation stops local observation without aborting Pi.
        """
        self._check_loop()
        return cast(
            "asyncio.Task[None]",
            start_collection(self.events(), self.limits, timeout=timeout, retain=False),
        )

    async def prompt_and_wait(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = 60.0,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> list[Event]:
        """Collect before sending; require successful acknowledgement and settlement.

        This observes session events, not a correlated or owned run. Model stop
        reasons remain events. Failure cancels local waits without aborting Pi.
        """
        self._check_loop()
        timer = asyncio.timeout_at(deadline(timeout))
        collection = self.collect_events(timeout=None)
        prompt = asyncio.create_task(
            self.prompt(message, images=images, timeout=command_timeout), name="pi-prompt"
        )
        try:
            async with timer:
                await asyncio.gather(prompt, collection)
                return collection.result()
        except TimeoutError as exc:
            if not timer.expired():
                raise
            raise PiTimeoutError(
                "Prompt collection deadline elapsed", command="prompt", uncertain=True
            ) from exc
        except PiUIHandlerError as exc:
            if self._ui_error is exc:
                self._ui_error = None
            raise
        finally:
            for task in (prompt, collection):
                if not task.done():
                    task.cancel()
            await asyncio.gather(prompt, collection, return_exceptions=True)

    def events(self) -> EventSubscription:
        """Subscribe on context entry to future events, including extension UI/errors."""
        return EventSubscription(self.limits, self._register, self._subscriptions.discard)

    def _register(self, subscription: EventSubscription) -> None:
        self._check_loop()
        if self._terminal_error is not None:
            raise self._terminal_error
        if self._closed:
            raise PiProcessError("Client is closed")
        self._subscriptions.add(subscription)

    def observe(
        self, *, stderr: bool = True, stdout: bool = False, rpc: bool = False
    ) -> ProcessObservation:
        """Observe selected process output; enter before start for lifetime coverage.

        Raises ValueError if no source is selected. Slow consumers raise
        PiSubscriptionOverflow. Close the client and drain this iterator before
        checking status.complete and status.error; terminal process failures are
        reported through status.error after output drains.
        """
        sources: set[OutputSource] = set()
        if stderr:
            sources.add("stderr")
        if stdout:
            sources.add("stdout")
        if rpc:
            sources.add("rpc")
        if not sources:
            raise ValueError("Select at least one observation source")
        return ProcessObservation(
            self.limits, self._register_observer, self._observations.discard, frozenset(sources)
        )

    def _register_observer(self, observer: ProcessObservation) -> None:
        self._check_loop()
        if self._closed or self._terminal_error is not None:
            raise PiProcessError("Cannot observe a closed or failed client")
        observer._status = ObservationStatus(
            started_at_ns=self._process_started_at_ns,
            from_start=self._process_started_at_ns is None,
        )
        self._observations.add(observer)

    def _on_output(self, source: OutputSource, data: bytes | dict[str, Any]) -> None:
        observers = [observer for observer in self._observations if source in observer._sources]
        if not observers:
            return
        receipt = time.time_ns()
        try:
            encoded = json.dumps(data) if isinstance(data, dict) else None
            size = len(encoded.encode("utf-8")) if encoded is not None else len(data)
            for observer in observers:
                # Decode separate dictionaries without deepcopy's lower recursion ceiling.
                value = json.loads(encoded) if encoded is not None else data
                observer._put(ProcessOutput(source, receipt, value), size)
        except (ValueError, RecursionError):
            for observer in observers:
                observer._finish(PiSubscriptionOverflow("RPC observation could not copy a record"))

    def _on_output_end(
        self, stdout_eof: bool, stderr_eof: bool, rpc_complete: bool, error: Exception | None
    ) -> None:
        for observer in tuple(self._observations):
            complete = observer.status.from_start
            if "stderr" in observer._sources:
                complete = complete and stderr_eof
            if observer._sources.intersection({"stdout", "rpc"}):
                complete = complete and stdout_eof
            if "rpc" in observer._sources:
                complete = complete and rpc_complete
            observer._status = replace(
                observer.status,
                ended_at_ns=time.time_ns(),
                stdout_eof=stdout_eof,
                stderr_eof=stderr_eof,
                rpc_complete=rpc_complete,
                complete=complete,
                error=self._close_error if self._closed else self._terminal_error or error,
                end_reason="process_end",
            )
            observer._finish()

    def _on_event(self, raw: dict[str, Any]) -> None:
        event = Event(raw)
        # Validate a recognized text update without restricting future variants.
        _ = event.text_delta
        encoded = json.dumps(raw)
        size = len(encoded.encode("utf-8"))
        for subscription in tuple(self._subscriptions):
            subscription._put(event, size)
        if self._owner is not None:
            self._owner._on_event(event, size)
        for key, listener in tuple(self._listeners.items()):
            if key not in self._listeners:
                continue
            try:
                # Listener mutation cannot change routing or another consumer's event.
                result = cast(Callable[[Event], object], listener)(Event(json.loads(encoded)))
                if inspect.iscoroutine(result):
                    result.close()
                    raise TypeError("Event listeners must be synchronous")
            except (Exception, asyncio.CancelledError) as exc:
                asyncio.get_running_loop().call_exception_handler(
                    {"message": "Pi event listener failed", "exception": exc}
                )
        if event.type == "session_info_changed":
            if "name" in raw and not isinstance(raw["name"], str):
                raise PiProtocolError("session_info_changed requires a string name when present")
            self._session = SessionInfo(
                self._session.session_id, self._session.session_file, raw.get("name")
            )
        if event.type == "extension_ui_request":
            if not isinstance(raw.get("method"), str) or not isinstance(raw.get("id"), str):
                raise PiProtocolError("Extension UI requests require string id and method")
            if self._ui_handler is None and raw["method"] not in _DIALOGS:
                return
            if (
                len(self._ui_tasks) >= self.limits.event_queue_size
                or self._ui_bytes + size > self.limits.event_queue_bytes
            ):
                assert self._transport is not None
                self._transport._fail(
                    PiUIHandlerError(
                        "Outstanding extension UI requests exceeded buffer limits; Pi is closed"
                    )
                )
                return
            task = asyncio.create_task(self._handle_ui(raw), name="pi-extension-ui")
            self._ui_tasks.add(task)
            self._ui_bytes += size
            task.add_done_callback(lambda done: self._ui_finished(done, size))

    def _ui_finished(self, task: asyncio.Task[None], size: int) -> None:
        self._ui_tasks.discard(task)
        self._ui_bytes -= size
        if not task.cancelled():
            task.exception()

    def _on_failure(self, error: Exception) -> None:
        if self._terminal_error is None:
            self._terminal_error = error
        error = self._terminal_error
        self._session = SessionInfo()
        self._listeners.clear()
        for task in tuple(self._ui_tasks):
            if task is not asyncio.current_task() and task is not self._close_initiator:
                task.cancel()
        for subscription in tuple(self._subscriptions):
            subscription._finish(error)
        if self._owner is not None:
            self._owner._fail(error)

    async def _handle_ui(self, raw: dict[str, Any]) -> None:
        method, request_id = raw.get("method"), raw.get("id")
        dialog = isinstance(method, str) and method in _DIALOGS
        try:
            if not isinstance(method, str) or not isinstance(request_id, str):
                raise PiProtocolError("Malformed extension UI request")
            response: dict[str, Any] = {"type": "extension_ui_response", "id": request_id}
            answer: UIValue = None
            if self._ui_handler is not None:
                timeout_ms = raw.get("timeout")
                deadline = timeout_ms / 1000 if isinstance(timeout_ms, (int, float)) else None
                timer = asyncio.timeout(deadline)
                try:
                    async with timer:
                        if inspect.iscoroutinefunction(self._ui_handler):
                            answer = await self._ui_handler(cast(ExtensionUIRequest, raw))
                        else:
                            answer_or_awaitable = await asyncio.to_thread(self._call_sync_ui, raw)
                            answer = (
                                await answer_or_awaitable
                                if inspect.isawaitable(answer_or_awaitable)
                                else answer_or_awaitable
                            )
                except TimeoutError:
                    if not timer.expired():
                        raise  # The callback itself failed, not the protocol deadline.
                if timer.expired():
                    # Pi treats expiry as cancellation. Also discard an answer
                    # returned by a callback that suppressed timeout cancellation.
                    answer = None
            if dialog:
                if answer is None:
                    response["cancelled"] = True
                elif method == "confirm" and isinstance(answer, bool):
                    response["confirmed"] = answer
                elif method != "confirm" and isinstance(answer, str):
                    response["value"] = answer
                else:
                    raise TypeError(
                        "UI handler must return bool for confirm, str for other dialogs, or None"
                    )
                if self._transport is not None and self._transport.running:
                    await self._transport.send_ui(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if (
                dialog
                and isinstance(request_id, str)
                and self._transport is not None
                and self._transport.running
            ):
                try:
                    await self._transport.send_ui(
                        {"type": "extension_ui_response", "id": request_id, "cancelled": True}
                    )
                except Exception:
                    pass
            error = PiUIHandlerError("Extension UI handler failed; inspect __cause__ for details")
            error.__cause__ = exc
            self._ui_error = error
            for subscription in tuple(self._subscriptions):
                subscription._finish(error)
            if self._owner is not None:
                self._owner._fail(error)

    def _call_sync_ui(self, raw: dict[str, Any]) -> UIValue | Awaitable[UIValue]:
        assert self._ui_handler is not None
        token = IN_SYNC_UI.set(True)
        try:
            return self._ui_handler(cast(ExtensionUIRequest, raw))
        finally:
            IN_SYNC_UI.reset(token)

    def _update_session(self, data: dict[str, Any]) -> None:
        if not isinstance(data.get("sessionId"), str):
            raise PiProtocolError("get_state did not contain a string sessionId")
        for key in ("isStreaming", "isCompacting"):
            if not isinstance(data.get(key), bool):
                raise PiProtocolError(f"get_state contained invalid {key}")
        count = data.get("pendingMessageCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise PiProtocolError("get_state contained invalid pendingMessageCount")
        for key in ("sessionFile", "sessionName"):
            if key in data and not isinstance(data[key], str):
                raise PiProtocolError(f"get_state contained invalid {key}")
        self._session = SessionInfo(
            data["sessionId"], data.get("sessionFile"), data.get("sessionName")
        )

    @staticmethod
    def _data(response: dict[str, Any]) -> dict[str, Any]:
        value = response.get("data")
        if not isinstance(value, dict):
            raise PiProtocolError("Pi response requires object data")
        return value

    async def request(
        self, command_type: str, *, timeout: Timeout = DEFAULT_TIMEOUT, **fields: Any
    ) -> dict[str, Any]:
        """Send a checked raw command, assigning its ID and enforcing run ownership.

        A timeout after submission has an uncertain outcome. Commands are never
        replayed. None disables the response deadline; omitted uses configured
        defaults (long commands have no deadline). Cancellation abandons the
        response wait; use abort() to stop low-level submitted work explicitly.
        """
        return await self._request(command_type, fields, timeout=timeout)

    async def _request(
        self,
        command: str,
        fields: dict[str, Any] | None = None,
        *,
        timeout: Timeout = DEFAULT_TIMEOUT,
        owner: RunStream | None = None,
    ) -> dict[str, Any]:
        self._check_loop()
        if not self.running or self._transport is None:
            raise PiProcessError("Pi is not running; use the client context or start() first")
        if self._owner is not None and owner is not self._owner and command not in _DURING_RUN:
            if not (
                command == "prompt"
                and (fields or {}).get("streamingBehavior") in {"steer", "followUp"}
            ):
                raise PiBusyError("Command conflicts with the active owned run")
        deadline = (
            (None if command in _LONG_COMMANDS else self.limits.command_timeout)
            if timeout is DEFAULT_TIMEOUT
            else timeout
        )
        if deadline is not None:
            _validate_timeout(deadline)

        def mark_submission() -> None:
            if owner is not None:
                owner._mark_submitted()
            elif self._owner is None:
                # Even rejection cannot prove extension preflight is idle.
                self._unowned_submission = True

        try:
            response = await self._transport.request(
                command,
                fields,
                timeout=deadline,
                before_write=(
                    mark_submission if command in {"prompt", "steer", "follow_up"} else None
                ),
            )
            if self._ui_error is not None:
                error, self._ui_error = self._ui_error, None
                raise error
            if command == "get_state":
                self._update_session(self._data(response))
            elif command in _SESSION_COMMANDS:
                # A mutation's result must not depend on an extra state query.
                # The legacy snapshot stays unknown until an explicit get_state().
                self._session = SessionInfo()
            return response
        except (PiTimeoutError, asyncio.CancelledError):
            if command in _SESSION_COMMANDS:
                self._session = SessionInfo()
            raise

    async def _object(
        self,
        command: str,
        fields: dict[str, Any] | None = None,
        *,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        return self._data(await self._request(command, fields, timeout=timeout))

    async def _list(
        self, command: str, key: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> list[Any]:
        value = (await self._object(command, timeout=timeout)).get(key)
        if not isinstance(value, list):
            raise PiProtocolError(f"{command} response requires a list in {key}")
        return value

    async def prompt(
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
        fields: dict[str, Any] = {"message": message}
        if images is not None:
            fields["images"] = images
        if streaming_behavior is not None:
            if streaming_behavior not in {"steer", "followUp"}:
                raise ValueError("streaming_behavior must be steer or followUp")
            fields["streamingBehavior"] = streaming_behavior
        await self._request("prompt", fields, timeout=timeout)

    async def steer(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        """Queue input for the next steering opportunity."""
        await self._request(
            "steer",
            {"message": message, **({"images": images} if images is not None else {})},
            timeout=timeout,
        )

    async def follow_up(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        """Queue input after the current response."""
        await self._request(
            "follow_up",
            {"message": message, **({"images": images} if images is not None else {})},
            timeout=timeout,
        )

    async def abort(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort current work using Pi semantics; queued work is not cleared implicitly."""
        await self._request("abort", timeout=timeout)

    async def clear_queue(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> QueueState:
        """Clear queued input and return the removed steering and follow-up text."""
        return cast(QueueState, await self._object("clear_queue", timeout=timeout))

    async def new_session(
        self, *, parent_session: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
        """Start a new session; inspect cancelled for an extension veto."""
        return cast(
            SessionChangeResult,
            await self._object(
                "new_session",
                {"parentSession": parent_session} if parent_session is not None else {},
                timeout=timeout,
            ),
        )

    async def get_state(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionState:
        """Read authoritative Pi state and refresh the cached session identity."""
        return cast(SessionState, await self._object("get_state", timeout=timeout))

    async def set_model(
        self, provider: str, model_id: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> Model:
        """Select a provider/model and return its full metadata."""
        return cast(
            Model,
            await self._object(
                "set_model", {"provider": provider, "modelId": model_id}, timeout=timeout
            ),
        )

    async def cycle_model(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ModelCycleResult | None:
        """Cycle models and return model, thinking level, and scope, or None."""
        response = await self._request("cycle_model", timeout=timeout)
        return (
            None if response.get("data") is None else cast(ModelCycleResult, self._data(response))
        )

    async def get_available_models(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[Model]:
        """List the models Pi makes available with their provider metadata."""
        return await self._list("get_available_models", "models", timeout=timeout)

    async def set_thinking_level(
        self, level: ThinkingLevel, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Request a thinking level for the current model."""
        await self._request("set_thinking_level", {"level": level}, timeout=timeout)

    async def cycle_thinking_level(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> ThinkingLevelCycleResult | None:
        """Return the complete thinking-level result, or None when unavailable."""
        response = await self._request("cycle_thinking_level", timeout=timeout)
        if response.get("data") is None:
            return None
        data = self._data(response)
        if not isinstance(data.get("level"), str):
            raise PiProtocolError("cycle_thinking_level requires a string level")
        return cast(ThinkingLevelCycleResult, data)

    async def get_available_thinking_levels(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> list[ThinkingLevel]:
        """List thinking levels available for the current model."""
        return await self._list("get_available_thinking_levels", "levels", timeout=timeout)

    async def set_steering_mode(
        self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Choose all queued steering messages or one at a time."""
        await self._request("set_steering_mode", {"mode": mode}, timeout=timeout)

    async def set_follow_up_mode(
        self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Choose all queued follow-up messages or one at a time."""
        await self._request("set_follow_up_mode", {"mode": mode}, timeout=timeout)

    async def compact(
        self, *, custom_instructions: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> CompactionResult:
        """Compact the conversation and return Pi's summary and token information."""
        return cast(
            CompactionResult,
            await self._object(
                "compact",
                {"customInstructions": custom_instructions}
                if custom_instructions is not None
                else {},
                timeout=timeout,
            ),
        )

    async def set_auto_compaction(
        self, enabled: bool, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Enable or disable Pi's automatic context compaction."""
        await self._request("set_auto_compaction", {"enabled": enabled}, timeout=timeout)

    async def set_auto_retry(self, enabled: bool, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Enable or disable Pi's automatic retry policy."""
        await self._request("set_auto_retry", {"enabled": enabled}, timeout=timeout)

    async def abort_retry(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort Pi's active retry sequence."""
        await self._request("abort_retry", timeout=timeout)

    async def bash(
        self,
        command: str,
        *,
        exclude_from_context: bool | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> BashResult:
        """Run Pi's bash command; output deltas are available through events()."""
        return cast(
            BashResult,
            await self._object(
                "bash",
                {
                    "command": command,
                    **(
                        {"excludeFromContext": exclude_from_context}
                        if exclude_from_context is not None
                        else {}
                    ),
                },
                timeout=timeout,
            ),
        )

    async def abort_bash(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Abort Pi's active bash execution."""
        await self._request("abort_bash", timeout=timeout)

    async def get_session_stats(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionStats:
        """Return Pi's current session message counts, token totals, and cost."""
        return cast(SessionStats, await self._object("get_session_stats", timeout=timeout))

    async def export_html(
        self, *, output_path: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> ExportHtmlResult:
        """Return the full export result, including path and unknown metadata."""
        data = await self._object(
            "export_html",
            {"outputPath": output_path} if output_path is not None else {},
            timeout=timeout,
        )
        if not isinstance(data.get("path"), str):
            raise PiProtocolError("export_html requires a string path")
        return cast(ExportHtmlResult, data)

    async def switch_session(
        self, session_path: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
        """Switch to a session path; inspect cancelled for an extension veto."""
        return cast(
            SessionChangeResult,
            await self._object("switch_session", {"sessionPath": session_path}, timeout=timeout),
        )

    async def fork(self, entry_id: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ForkResult:
        """Fork at an eligible entry; a veto can omit the returned editable text."""
        return cast(ForkResult, await self._object("fork", {"entryId": entry_id}, timeout=timeout))

    async def clone(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionChangeResult:
        """Clone the current session; inspect cancelled for an extension veto."""
        return cast(SessionChangeResult, await self._object("clone", timeout=timeout))

    async def get_fork_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[ForkMessage]:
        """List eligible message entry IDs and text for choosing a fork point."""
        return await self._list("get_fork_messages", "messages", timeout=timeout)

    async def get_entries(
        self, *, since: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> EntriesResult:
        """Return saved entries after an optional entry ID and the current leaf ID."""
        return cast(
            EntriesResult,
            await self._object(
                "get_entries", {"since": since} if since is not None else {}, timeout=timeout
            ),
        )

    async def get_tree(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> TreeResult:
        """Return the recursive session tree and nullable selected leaf ID."""
        return cast(TreeResult, await self._object("get_tree", timeout=timeout))

    async def get_last_assistant_text(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> str | None:
        """Query session history for usable assistant text, or None when absent."""
        value = (await self._object("get_last_assistant_text", timeout=timeout)).get("text")
        if value is not None and not isinstance(value, str):
            raise PiProtocolError("get_last_assistant_text returned invalid text")
        return value

    async def set_session_name(self, name: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        """Set the session name; query get_state() explicitly for updated identity."""
        await self._request("set_session_name", {"name": name}, timeout=timeout)

    async def get_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[AgentMessage]:
        """Return Pi's current conversation messages."""
        return await self._list("get_messages", "messages", timeout=timeout)

    async def get_commands(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[SlashCommand]:
        """List extension, prompt-template, and skill commands with source information."""
        return await self._list("get_commands", "commands", timeout=timeout)

    def stream(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = None,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> RunStream:
        """Own a run in an async context; iterate events or await result() to drain."""
        from ._runs import RunStream

        return RunStream(
            self, message, images=images, timeout=timeout, command_timeout=command_timeout
        )

    async def run(
        self,
        message: str,
        *,
        images: list[ImageContent] | None = None,
        timeout: float | None = None,
        command_timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Submit a prompt and wait through retries/continuations until agent_settled."""
        stream = self.stream(
            message, images=images, timeout=timeout, command_timeout=command_timeout
        )
        stream._retain_events = False
        async with stream:
            return await stream.result()
