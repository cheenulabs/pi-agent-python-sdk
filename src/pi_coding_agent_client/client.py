"""Async lifecycle, explicit RPC methods, and extension interaction."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import math
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

from ._events import EventSubscription
from ._launch import check_version, executable_argv, validate_extra_args
from ._transport import Transport
from .errors import PiBusyError, PiProcessError, PiProtocolError, PiTimeoutError, PiUIHandlerError
from .types import (
    AcceptanceReceipt,
    AgentMessage,
    BashResult,
    CompactionResult,
    EntriesResult,
    Event,
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
    TreeResult,
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
        self._ui_tasks: set[asyncio.Task[None]] = set()
        self._ui_bytes = 0
        self._ui_error: PiUIHandlerError | None = None
        self._owner: RunStream | None = None
        self._session = SessionInfo()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._starting = False
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
        if self._loop is not None and asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Use the client only from the event loop that started it")

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
        self._loop = asyncio.get_running_loop()
        self._starting = True
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
                )
                await self._transport.start([*argv, *self._args], cwd=self._cwd, env=child_env)
                response = await self._transport.request(
                    "get_state", timeout=self.limits.startup_timeout
                )
                self._update_session(self._data(response))
        except TimeoutError as exc:
            await self.aclose()
            raise PiTimeoutError("Pi startup timed out", uncertain=False) from exc
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._starting = False

    async def aclose(self) -> None:
        """Wake all operations and reap the child; repeated calls are safe."""
        self._check_loop()
        self._closed = True
        if self._transport is not None:
            await self._transport.aclose()
        tasks = tuple(task for task in self._ui_tasks if task is not asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def events(self) -> EventSubscription:
        """Subscribe on context entry to future events, including extension UI/errors."""
        return EventSubscription(self.limits, self._register, self._subscriptions.discard)

    def _register(self, subscription: EventSubscription) -> None:
        self._check_loop()
        if not self.running:
            raise PiProcessError("Start Pi before subscribing to events")
        self._subscriptions.add(subscription)

    def _on_event(self, raw: dict[str, Any]) -> None:
        event = Event(raw)
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
        for subscription in tuple(self._subscriptions):
            subscription._put(event, size)
        if self._owner is not None:
            self._owner._on_event(event, size)
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
        self._session = SessionInfo()
        for task in tuple(self._ui_tasks):
            if task is not asyncio.current_task():
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
                async with asyncio.timeout(deadline):
                    if inspect.iscoroutinefunction(self._ui_handler):
                        answer = await self._ui_handler(cast(ExtensionUIRequest, raw))
                    else:
                        answer_or_awaitable = await asyncio.to_thread(self._call_sync_ui, raw)
                        answer = (
                            await answer_or_awaitable
                            if inspect.isawaitable(answer_or_awaitable)
                            else answer_or_awaitable
                        )
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
        if deadline is not None and (
            not isinstance(deadline, (int, float))
            or isinstance(deadline, bool)
            or not math.isfinite(deadline)
            or deadline <= 0
        ):
            raise ValueError("timeout must be a positive finite number or None")
        try:
            response = await self._transport.request(command, fields, timeout=deadline)
            if self._ui_error is not None:
                error, self._ui_error = self._ui_error, None
                raise error
            if command == "get_state":
                self._update_session(self._data(response))
            elif command in _SESSION_COMMANDS:
                self._session = SessionInfo()
                state = await self._transport.request(
                    "get_state", timeout=self.limits.command_timeout
                )
                self._update_session(self._data(state))
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
    ) -> AcceptanceReceipt:
        """Wait for acceptance only; handled commands may never start an agent run."""
        fields: dict[str, Any] = {"message": message}
        if images is not None:
            fields["images"] = images
        if streaming_behavior is not None:
            if streaming_behavior not in {"steer", "followUp"}:
                raise ValueError("streaming_behavior must be steer or followUp")
            fields["streamingBehavior"] = streaming_behavior
        return cast(AcceptanceReceipt, await self._request("prompt", fields, timeout=timeout))

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
        return cast(QueueState, await self._object("clear_queue", timeout=timeout))

    async def new_session(
        self, *, parent_session: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
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
        return cast(
            Model,
            await self._object(
                "set_model", {"provider": provider, "modelId": model_id}, timeout=timeout
            ),
        )

    async def cycle_model(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ModelCycleResult | None:
        response = await self._request("cycle_model", timeout=timeout)
        return (
            None if response.get("data") is None else cast(ModelCycleResult, self._data(response))
        )

    async def get_available_models(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[Model]:
        return await self._list("get_available_models", "models", timeout=timeout)

    async def set_thinking_level(
        self, level: ThinkingLevel, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        await self._request("set_thinking_level", {"level": level}, timeout=timeout)

    async def cycle_thinking_level(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> ThinkingLevel | None:
        response = await self._request("cycle_thinking_level", timeout=timeout)
        if response.get("data") is None:
            return None
        value = self._data(response).get("level")
        if not isinstance(value, str):
            raise PiProtocolError("cycle_thinking_level requires a string level")
        return cast(ThinkingLevel, value)

    async def get_available_thinking_levels(
        self, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> list[ThinkingLevel]:
        return await self._list("get_available_thinking_levels", "levels", timeout=timeout)

    async def set_steering_mode(
        self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        await self._request("set_steering_mode", {"mode": mode}, timeout=timeout)

    async def set_follow_up_mode(
        self, mode: QueueMode, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        await self._request("set_follow_up_mode", {"mode": mode}, timeout=timeout)

    async def compact(
        self, *, custom_instructions: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> CompactionResult:
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
        await self._request("set_auto_compaction", {"enabled": enabled}, timeout=timeout)

    async def set_auto_retry(self, enabled: bool, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        await self._request("set_auto_retry", {"enabled": enabled}, timeout=timeout)

    async def abort_retry(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
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
        await self._request("abort_bash", timeout=timeout)

    async def get_session_stats(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionStats:
        return cast(SessionStats, await self._object("get_session_stats", timeout=timeout))

    async def export_html(
        self, *, output_path: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> str:
        data = await self._object(
            "export_html",
            {"outputPath": output_path} if output_path is not None else {},
            timeout=timeout,
        )
        if not isinstance(data.get("path"), str):
            raise PiProtocolError("export_html requires a string path")
        return cast(str, data["path"])

    async def switch_session(
        self, session_path: str, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> SessionChangeResult:
        return cast(
            SessionChangeResult,
            await self._object("switch_session", {"sessionPath": session_path}, timeout=timeout),
        )

    async def fork(self, entry_id: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> ForkResult:
        return cast(ForkResult, await self._object("fork", {"entryId": entry_id}, timeout=timeout))

    async def clone(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> SessionChangeResult:
        return cast(SessionChangeResult, await self._object("clone", timeout=timeout))

    async def get_fork_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[ForkMessage]:
        return await self._list("get_fork_messages", "messages", timeout=timeout)

    async def get_entries(
        self, *, since: str | None = None, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> EntriesResult:
        return cast(
            EntriesResult,
            await self._object(
                "get_entries", {"since": since} if since is not None else {}, timeout=timeout
            ),
        )

    async def get_tree(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> TreeResult:
        return cast(TreeResult, await self._object("get_tree", timeout=timeout))

    async def get_last_assistant_text(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> str | None:
        value = (await self._object("get_last_assistant_text", timeout=timeout)).get("text")
        if value is not None and not isinstance(value, str):
            raise PiProtocolError("get_last_assistant_text returned invalid text")
        return value

    async def set_session_name(self, name: str, *, timeout: Timeout = DEFAULT_TIMEOUT) -> None:
        await self._request("set_session_name", {"name": name}, timeout=timeout)

    async def get_messages(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[AgentMessage]:
        return await self._list("get_messages", "messages", timeout=timeout)

    async def get_commands(self, *, timeout: Timeout = DEFAULT_TIMEOUT) -> list[SlashCommand]:
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
        async with self.stream(
            message, images=images, timeout=timeout, command_timeout=command_timeout
        ) as stream:
            return await stream.result()
