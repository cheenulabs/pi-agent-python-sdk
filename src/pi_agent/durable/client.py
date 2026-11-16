"""Async Durable protocol client, using the SDK's owned-process transport."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Self, cast

from .._launch import child_env, executable_argv
from .._transport import Transport
from ..client import DEFAULT_TIMEOUT, Timeout
from ..errors import PiProcessError, PiProtocolError, PiTimeoutError, PiVersionError
from ..types import Limits, _validate_timeout
from .types import (
    AgentOptions,
    ConversationId,
    EntriesFields,
    OpenFields,
    RootFields,
    SettledSubmission,
    Storage,
    SubmissionId,
    SubmitFields,
    WatchUpdate,
    WhenBusy,
)
from .watch import WatchSubscription

_LOG = logging.getLogger("pi_agent.durable")
_HOST_HELP = "Pi Durable requires Node >=22.19 and an explicit host_command"


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PiProtocolError("Durable response requires an object")
    return cast(dict[str, Any], value)


def _integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PiProtocolError("Durable response requires an integer ID")
    return value


class AsyncDurableClient:
    """Single-use experimental client. Construction starts no process.

    The caller supplies a host command and owns single-writer access to storage.
    Close shuts down the host; a new client resumes unfinished persisted work.
    No command is automatically retried. Retry uncertain submissions only with
    the same caller-provided request ID.
    """

    def __init__(
        self,
        storage_path: str | os.PathLike[str] | None,
        *,
        host_command: Sequence[str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str | None] | None = None,
        inherit_env: bool = True,
        limits: Limits | None = None,
        coding_tools: bool = True,
        settings: Mapping[str, Any] | None = None,
        faux: Sequence[str | Mapping[str, Any]] | None = None,
        faux_tokens_per_second: float | None = None,
    ) -> None:
        self._storage: Storage = (
            {"kind": "memory"}
            if storage_path is None
            else {"kind": "sqlite", "path": os.fspath(storage_path)}
        )
        self._host_command = list(host_command) if host_command is not None else None
        self._cwd = os.fspath(cwd) if cwd is not None else None
        self._env = dict(env or {})
        self._inherit_env = inherit_env
        self._limits = limits or Limits()
        self._open_fields: OpenFields = {
            "storage": self._storage,
            "codingTools": coding_tools,
            "maxRecordBytes": self._limits.max_record_bytes,
        }
        if settings is not None:
            self._open_fields["settings"] = dict(settings)
        if faux is not None:
            self._open_fields["faux"] = [s if isinstance(s, str) else dict(s) for s in faux]
        if faux_tokens_per_second is not None:
            self._open_fields["fauxTokensPerSecond"] = faux_tokens_per_second
        self._transport: Transport | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_task: asyncio.Task[Any] | None = None
        self._startup_done = asyncio.Event()
        self._startup_done.set()
        self._close_task: asyncio.Task[None] | None = None
        self._close_initiator: asyncio.Task[Any] | None = None
        self._used = False
        self._closed = False
        self._ready = False
        self._host_pid: int | None = None
        self._pi_durable_version: str | None = None
        self._watches: dict[str, WatchSubscription] = {}
        self._background: set[asyncio.Task[None]] = set()

    @property
    def limits(self) -> Limits:
        return self._limits

    @property
    def running(self) -> bool:
        return self._ready and self._transport is not None and self._transport.running

    @property
    def host_pid(self) -> int | None:
        return self._host_pid

    @property
    def pi_durable_version(self) -> str | None:
        return self._pi_durable_version

    @property
    def stderr_tail(self) -> str:
        return self._transport.stderr_tail if self._transport is not None else ""

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Use AsyncDurableClient on the loop that started it")
        self._loop = loop

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
        """Resolve and launch the host, negotiate protocol v0, and resume storage."""
        self._check_loop()
        if self._used or self._closed:
            raise PiProcessError("Clients are single-use; create a new Durable client")
        self._used = True
        self._startup_task = asyncio.current_task()
        self._startup_done.clear()
        spawned = False
        try:
            async with asyncio.timeout(self.limits.startup_timeout):
                environment = child_env(self._inherit_env, self._env)
                if not self._host_command:
                    raise PiProcessError(_HOST_HELP)
                try:
                    argv = executable_argv(self._host_command, environment)
                except PiProcessError as exc:
                    raise PiProcessError(_HOST_HELP) from exc
                if self._cwd is not None:
                    # Resolve once in the caller's launch-time directory. Passing
                    # a relative cwd again to the agent would apply it twice.
                    self._cwd = await asyncio.to_thread(os.path.abspath, self._cwd)
                self._transport = Transport(
                    limits=self.limits, on_event=self._on_event, on_failure=self._on_failure
                )
                await self._transport.start(argv, cwd=self._cwd, env=environment)
                spawned = True
                hello = await self._request("hello", {}, self.limits.startup_timeout, startup=True)
                protocol = _integer(hello.get("protocol"))
                if protocol != 0:
                    raise PiVersionError("Unsupported Pi Durable host protocol; expected 0")
                self._host_pid = _integer(hello.get("pid"))
                version = hello.get("piDurable")
                if not isinstance(version, str):
                    raise PiProtocolError("Durable hello requires a version string")
                self._pi_durable_version = version
                await self._request(
                    "open", dict(self._open_fields), self.limits.startup_timeout, startup=True
                )
                self._ready = True
        except BaseException as exc:
            self._closed = True
            if self._transport is not None:
                await self._transport.aclose()
            if isinstance(exc, TimeoutError):
                raise PiTimeoutError("Pi Durable startup timed out", uncertain=False) from exc
            if isinstance(exc, PiProcessError) and spawned:
                raise PiProcessError(
                    "The Durable host exited during startup; check host_command and run "
                    "npm ci --prefix durable-host. Set Limits(stderr_tail_bytes=...) "
                    "to capture host stderr.",
                    returncode=exc.returncode,
                ) from exc
            raise
        finally:
            self._startup_task = None
            self._startup_done.set()

    async def aclose(self) -> None:
        """Shut down and reap the host; repeated calls join shielded cleanup.

        Cancelling the caller does not cancel teardown. A later aclose() can
        await that same cleanup to completion.
        """
        self._check_loop()
        if self._close_task is None:
            self._closed = True
            self._ready = False
            self._close_initiator = asyncio.current_task()
            self._close_task = asyncio.create_task(self._finish_close(), name="pi-durable-close")
        await asyncio.shield(self._close_task)

    async def _finish_close(self) -> None:
        try:
            startup = self._startup_task
            if startup is not None and startup is not self._close_initiator and not startup.done():
                startup.cancel()
                # start() can be nested in an application task whose finally
                # also awaits us. Join startup cleanup, never that whole task.
                await self._startup_done.wait()
            for subscription in tuple(self._watches.values()):
                subscription._finish()
            if self._transport is not None:
                # EOF stops watches upstream and wakes any pending unwatch.
                # Never delay process teardown waiting for an unwatch reply.
                await self._transport.aclose()
        finally:
            if self._background:
                await asyncio.gather(*self._background, return_exceptions=True)
            self._close_initiator = None

    def _on_event(self, record: dict[str, Any]) -> None:
        event_type = record.get("type")
        watch_id = record.get("watchId")
        if event_type in {"durable_watch", "durable_watch_end"}:
            subscription = self._watches.get(watch_id) if isinstance(watch_id, str) else None
            if subscription is None:
                return
            if event_type == "durable_watch_end":
                if not isinstance(record.get("kind"), str):
                    raise PiProtocolError("Malformed Durable watch end")
                subscription._finish()
                return
            entries, live = record.get("entries"), record.get("live")
            if (
                not isinstance(entries, list)
                or any(not isinstance(entry, dict) for entry in entries)
                or (live is not None and not isinstance(live, dict))
                or not isinstance(record.get("gap"), bool)
                or not isinstance(record.get("snapshot"), bool)
                or "live" not in record
            ):
                raise PiProtocolError("Malformed Durable watch update")
            subscription._put(
                WatchUpdate(entries, live, record["gap"], record["snapshot"], record),
                len(json.dumps(record).encode("utf-8")),
            )
            return
        if event_type in {"durable_report", "durable_protocol_error"}:
            # Never log payloads, messages, conversations, or credentials.
            marker = record.get("code", record.get("kind"))
            _LOG.debug("%s %s", event_type, marker if isinstance(marker, str) else None)

    def _on_failure(self, error: Exception) -> None:
        self._ready = False
        for subscription in tuple(self._watches.values()):
            subscription._finish(error)

    def _track_unwatch(self, watch_id: str) -> asyncio.Task[None]:
        async def cleanup() -> None:
            try:
                await self._request("unwatch", {"watchId": watch_id}, self.limits.cleanup_timeout)
            except Exception:
                pass  # Best effort: EOF also stops every watch on a dead/closing host.

        task = asyncio.create_task(cleanup(), name="pi-durable-unwatch")
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    def watch(self, conversation_id: ConversationId) -> WatchSubscription:
        """Return a bounded context/iterator; first update is the current snapshot.

        Overflow raises PiSubscriptionOverflow and unwatches. Re-enter a fresh
        watch to resume; gap=True requires an explicit entries() recovery read.
        """
        return WatchSubscription(self, conversation_id)

    async def _request(
        self,
        command: str,
        fields: dict[str, Any],
        timeout: Timeout,
        *,
        startup: bool = False,
        read_only: bool = False,
    ) -> dict[str, Any]:
        self._check_loop()
        if self._closed or (not startup and not self.running) or self._transport is None:
            raise PiProcessError("Pi Durable host is not running")
        deadline = self.limits.command_timeout if timeout is DEFAULT_TIMEOUT else timeout
        if deadline is not None:
            _validate_timeout(deadline)
        try:
            response = await self._transport.request(command, fields, timeout=deadline)
        except PiTimeoutError as exc:
            if not read_only:
                raise
            raise PiTimeoutError(
                "Pi Durable read timed out",
                command=exc.command,
                request_id=exc.request_id,
                uncertain=False,
            ) from exc
        return _object(response.get("data"))

    async def root(
        self,
        *,
        model: Mapping[str, str] | None = None,
        cwd: str | None = None,
        thinking_level: str | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> ConversationId:
        """Get/create the root; agent options affect only its first creation."""
        agent: AgentOptions = {}
        if model is not None:
            agent["model"] = dict(model)
        agent_cwd = cwd if cwd is not None else self._cwd
        if agent_cwd is not None:
            agent["cwd"] = agent_cwd
        if thinking_level is not None:
            agent["thinkingLevel"] = thinking_level
        fields: RootFields = {"agent": agent} if agent else {}
        return _integer((await self._request("root", dict(fields), timeout)).get("conversationId"))

    async def submit(
        self,
        conversation_id: ConversationId,
        content: str,
        *,
        request_id: str,
        when_busy: WhenBusy | None = None,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> SubmissionId:
        """Submit idempotently using a non-empty caller key scoped to the conversation."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a non-empty string")
        fields: SubmitFields = {
            "conversationId": conversation_id,
            "content": content,
            "requestId": request_id,
        }
        if when_busy is not None:
            fields["whenBusy"] = when_busy
        return _integer((await self._request("submit", dict(fields), timeout)).get("submissionId"))

    async def wait(
        self, submission_id: SubmissionId, *, timeout: float | None = None
    ) -> SettledSubmission:
        """Wait locally for settlement; a timeout does not abort upstream work."""
        data = await self._request("wait", {"submissionId": submission_id}, timeout, read_only=True)
        raw = _object(data.get("submission"))
        status, reason = raw.get("status"), raw.get("reason")
        if (
            not isinstance(status, str)
            or status not in {"done", "unanswered"}
            or (reason is not None and not isinstance(reason, str))
        ):
            raise PiProtocolError("Malformed Durable settled submission")
        return SettledSubmission(cast(Any, status), reason, raw)

    async def entries(
        self,
        conversation_id: ConversationId,
        *,
        limit: int = 50,
        timeout: Timeout = DEFAULT_TIMEOUT,
    ) -> list[dict[str, Any]]:
        """Read the newest entries, ordered oldest to newest, retaining unknown fields."""
        fields: EntriesFields = {"conversationId": conversation_id, "limit": limit}
        data = await self._request("entries", dict(fields), timeout, read_only=True)
        entries = data.get("entries")
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise PiProtocolError("Malformed Durable entries")
        return cast(list[dict[str, Any]], entries)

    async def abort(
        self, conversation_id: ConversationId, *, timeout: Timeout = DEFAULT_TIMEOUT
    ) -> None:
        """Abort upstream work and wait for the conversation to become idle."""
        await self._request("abort", {"conversationId": conversation_id}, timeout)
