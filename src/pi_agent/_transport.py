"""Owned subprocess I/O. Only this module reads Pi's stdout or writes stdin."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import PiCommandError, PiProcessError, PiProtocolError, PiTimeoutError
from .types import Limits


async def _wait_for_exit(process: asyncio.subprocess.Process) -> None:
    """Observe child exit without waiting for inherited pipes to reach EOF."""
    while process.returncode is None:  # noqa: ASYNC110 - asyncio exposes no pipe-independent exit event
        await asyncio.sleep(0.01)


def _close_process_pipes(process: asyncio.subprocess.Process) -> None:
    """Release this process's pipe handles after the owned child has exited."""
    assert process.returncode is not None
    # StreamReader has no public close(). Isolate the asyncio implementation
    # seam needed when a descendant retains its own copies of the pipes. The
    # owned child has exited, so close() cannot signal it or any descendants.
    process._transport.close()  # type: ignore[attr-defined]


@dataclass
class _Pending:
    command: str
    future: asyncio.Future[dict[str, Any]]


class Transport:
    """Route checked responses and unsolicited events from one owned child."""

    def __init__(
        self,
        *,
        limits: Limits,
        on_event: Callable[[dict[str, Any]], None],
        on_failure: Callable[[Exception], None],
        on_stderr: Callable[[bytes], None] | None = None,
        on_output_end: Callable[[bool, Exception | None], None] | None = None,
    ) -> None:
        self._limits = limits
        self._on_event = on_event
        self._on_failure = on_failure
        self._on_stderr = on_stderr
        self._on_output_end = on_output_end
        self._stderr_eof = False
        self._process: asyncio.subprocess.Process | None = None
        self._spawning: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._pending: dict[str, _Pending] = {}
        self._next_id = 0
        self._write_lock = asyncio.Lock()
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[None] | None = None
        self._exit_monitor: asyncio.Task[None] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._failure: Exception | None = None
        self._stderr = bytearray()
        self._stdout_buffer = bytearray()

    @property
    def running(self) -> bool:
        return (
            self._process is not None and self._process.returncode is None and self._failure is None
        )

    @property
    def stderr_tail(self) -> str:
        """Opt-in bounded diagnostic text; never included in exceptions."""
        return self._stderr.decode("utf-8", errors="replace")

    async def start(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        if self._spawning is not None or self._failure is not None:
            raise PiProcessError("Transport cannot be started twice")
        if not argv:
            raise ValueError("argv cannot be empty")
        try:
            self._spawning = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                ),
                name="pi-spawn",
            )
            # Keep ownership of a child created just as the caller is cancelled.
            self._process = await asyncio.shield(self._spawning)
        except asyncio.CancelledError:
            await self.aclose()
            raise
        except (OSError, ValueError) as exc:
            error = PiProcessError("Could not start Pi subprocess")
            self._fail(error)
            raise error from exc
        if self._failure is not None:
            await self.aclose()
            raise self._failure
        self._reader = asyncio.create_task(self._read_stdout(), name="pi-stdout")
        self._stderr_reader = asyncio.create_task(self._read_stderr(), name="pi-stderr")
        self._exit_monitor = asyncio.create_task(self._monitor_exit(), name="pi-exit")

    async def request(
        self,
        command: str,
        fields: dict[str, Any] | None = None,
        *,
        timeout: float | None = 30,  # noqa: ASYNC109 - per-response API, distinct from write bound
    ) -> dict[str, Any]:
        if not isinstance(command, str) or not command:
            raise ValueError("command must be a nonempty string")
        if fields is not None and {"id", "type"}.intersection(fields):
            raise ValueError("Request fields cannot override id or type")
        self._check_running()
        self._next_id += 1
        request_id = str(self._next_id)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        # A fast child can respond while drain() is still suspended.
        self._pending[request_id] = _Pending(command, future)
        try:
            await self._write({"type": command, "id": request_id, **(fields or {})})
            try:
                # Keep cancellation on this task: wait_for can lose cancellation
                # when its separate waiter completes at the same time on Python 3.11.
                async with asyncio.timeout(timeout):
                    return await asyncio.shield(future)
            except TimeoutError as exc:
                raise PiTimeoutError(
                    "Pi response timed out; the operation may still be running",
                    command=command,
                    request_id=request_id,
                    uncertain=True,
                ) from exc
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # A failed write can race a reader failure that rejected the future.
                future.exception()

    async def send_ui(self, record: dict[str, Any]) -> None:
        """Send a dialog reply with its original ID, without awaiting an ack."""
        if record.get("type") != "extension_ui_response" or not isinstance(record.get("id"), str):
            raise ValueError("UI replies require type extension_ui_response and a string id")
        await self._write(record)

    def _check_running(self) -> None:
        if self._failure is not None:
            raise self._failure
        if not self.running:
            raise PiProcessError("Pi subprocess is not running")

    async def _write(self, record: dict[str, Any]) -> None:
        data = json.dumps(
            record, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(data) > self._limits.max_record_bytes:
            raise ValueError("Outbound JSON record exceeds max_record_bytes")
        wrote = False
        try:
            # Bound lock acquisition too: a wedged pipe must not queue writers forever.
            async with asyncio.timeout(self._limits.command_timeout):
                async with self._write_lock:
                    self._check_running()
                    assert self._process is not None and self._process.stdin is not None
                    wrote = True
                    self._process.stdin.write(data + b"\n")
                    await self._process.stdin.drain()
        except TimeoutError as exc:
            error = PiTimeoutError("Pi stdin write timed out", uncertain=wrote)
            if wrote:
                self._fail(error)
            raise error from exc
        except asyncio.CancelledError:
            if wrote:
                self._fail(PiProcessError("Pi stdin write was interrupted"))
            raise
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            process_error = PiProcessError("Pi stdin closed while writing")
            self._fail(process_error)
            raise process_error from exc

    async def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        buffer = self._stdout_buffer
        try:
            while chunk := await self._process.stdout.read(65536):
                buffer.extend(chunk)
                offset = 0
                while (end := buffer.find(b"\n", offset)) >= 0:
                    self._record(bytes(buffer[offset:end]))
                    offset = end + 1
                if offset:
                    del buffer[:offset]
                if len(buffer) > self._limits.max_record_bytes:
                    raise PiProtocolError("Pi JSON record exceeds max_record_bytes")
            if buffer:
                self._record(bytes(buffer))
                buffer.clear()
            # EOF itself is terminal even if an extension left the process alive.
            self._fail(PiProcessError("Pi stdout closed", returncode=self._process.returncode))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _monitor_exit(self) -> None:
        assert self._process is not None
        await _wait_for_exit(self._process)
        # Let already-ready stdout callbacks run before declaring requests lost.
        # A descendant may retain the pipe, so EOF cannot be our exit signal.
        await asyncio.sleep(0)
        if self._failure is None:
            try:
                if self._stdout_buffer:
                    self._record(bytes(self._stdout_buffer))
                    self._stdout_buffer.clear()
            except Exception as exc:
                self._fail(exc)
                return
            self._fail(PiProcessError("Pi subprocess exited", returncode=self._process.returncode))

    def _record(self, data: bytes) -> None:
        if data.endswith(b"\r"):
            data = data[:-1]
        if len(data) > self._limits.max_record_bytes:
            raise PiProtocolError("Pi JSON record exceeds max_record_bytes")
        if not data:
            return
        try:
            record = json.loads(data.decode("utf-8"), parse_constant=self._invalid_constant)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise PiProtocolError("Pi emitted invalid UTF-8 JSON") from exc
        if not isinstance(record, dict) or not isinstance(record.get("type"), str):
            raise PiProtocolError("Pi record requires an object with a string type")
        if record["type"] != "response":
            self._on_event(record)
            return
        request_id = record.get("id")
        if (
            not isinstance(record.get("command"), str)
            or not isinstance(record.get("success"), bool)
            or (request_id is not None and not isinstance(request_id, str))
            or (record.get("success") is False and not isinstance(record.get("error"), str))
        ):
            raise PiProtocolError("Malformed Pi response envelope")
        if request_id is None:
            raise PiProtocolError("Pi emitted an uncorrelated response")
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            # Late and duplicate replies are not events and cannot match future IDs.
            return
        if pending.command != record["command"]:
            raise PiProtocolError("Pi response command does not match its request")
        if record["success"]:
            pending.future.set_result(record)
        else:
            pending.future.set_exception(
                PiCommandError(pending.command, record["error"], request_id=request_id)
            )

    @staticmethod
    def _invalid_constant(value: str) -> None:
        raise ValueError(f"Non-JSON numeric constant: {value}")

    async def _read_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while chunk := await self._process.stderr.read(65536):
                if self._on_stderr is not None:
                    self._on_stderr(chunk)
                if self._limits.stderr_tail_bytes:
                    self._stderr.extend(chunk)
                    del self._stderr[: -self._limits.stderr_tail_bytes]
            self._stderr_eof = True
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(PiProcessError("Could not drain Pi stderr"))

    def _fail(self, error: Exception) -> None:
        if self._failure is not None:
            return
        self._failure = error
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_exception(error)
        # Start teardown before callbacks so their failure cannot orphan the child.
        self._closing = asyncio.create_task(self._finish_close(), name="pi-close")
        self._on_failure(error)

    async def aclose(self) -> None:
        """Close stdin, then terminate/kill as necessary and reap the child."""
        self._fail(PiProcessError("Pi client closed"))
        assert self._closing is not None
        await asyncio.shield(self._closing)

    async def _finish_close(self) -> None:
        discard: asyncio.Task[None] | None = None
        stderr_eof = False
        try:
            if self._spawning is not None:
                try:
                    self._process = await self._spawning
                except (OSError, ValueError):
                    return
            process = self._process
            if process is not None:
                # Once terminal, discard stdout but keep draining it. A full pipe can
                # prevent asyncio's process.wait() finishing even after the child dies.
                if self._reader is not None:
                    self._reader.cancel()
                    await asyncio.gather(self._reader, return_exceptions=True)
                if process.stdout is not None:
                    discard = asyncio.create_task(self._discard(process.stdout))
                if self._stderr_reader is None:
                    self._stderr_reader = asyncio.create_task(self._read_stderr())
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    await asyncio.wait_for(_wait_for_exit(process), self._limits.cleanup_timeout)
                except TimeoutError:
                    if process.returncode is None:
                        try:
                            process.terminate()
                        except ProcessLookupError:
                            pass
                    try:
                        await asyncio.wait_for(
                            _wait_for_exit(process), self._limits.cleanup_timeout
                        )
                    except TimeoutError:
                        if process.returncode is None:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                        await _wait_for_exit(process)
                # Give received shutdown diagnostics a bounded chance to reach EOF.
                # Descendants may retain the pipe; that is explicitly incomplete.
                if self._stderr_reader is not None:
                    await asyncio.wait({self._stderr_reader}, timeout=self._limits.cleanup_timeout)
                stderr_eof = self._stderr_eof
                _close_process_pipes(process)
                await process.wait()
        finally:
            tasks = [
                task
                for task in (self._reader, self._stderr_reader, self._exit_monitor, discard)
                if task is not None
            ]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._on_output_end is not None:
                self._on_output_end(stderr_eof, self._failure)

    @staticmethod
    async def _discard(stream: asyncio.StreamReader) -> None:
        while await stream.read(65536):
            pass
