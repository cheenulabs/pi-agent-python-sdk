"""Exercise actual OS pipes with a child independent of the implementation."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from pi_agent._transport import Transport
from pi_agent.errors import (
    PiCommandError,
    PiProcessError,
    PiProtocolError,
    PiTimeoutError,
)
from pi_agent.types import Limits

FAKE = str(Path(__file__).with_name("fake_pi.py"))


@pytest_asyncio.fixture
async def transport() -> AsyncIterator[
    tuple[Transport, asyncio.Queue[dict[str, Any]], list[Exception]]
]:
    events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    failures: list[Exception] = []
    transport = Transport(limits=Limits(), on_event=events.put_nowait, on_failure=failures.append)
    await transport.start([sys.executable, FAKE])
    try:
        yield transport, events, failures
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_fragmented_unicode_coalesced_events_and_early_reply(transport: Any) -> None:
    client, events, _ = transport
    reply = await client.request("fragment")
    assert reply["data"] == "é\u2028\u2029"
    assert (await client.request("coalesce"))["success"]
    assert await events.get() == {"type": "new_future_event", "extra": True}
    assert (await client.request("echo", {"data": {"nul": "\0"}}))["data"] == {"nul": "\0"}


@pytest.mark.asyncio
async def test_out_of_order_responses_and_duplicate_ids(transport: Any) -> None:
    client, events, _ = transport
    first = asyncio.create_task(client.request("hold", {"data": 1}))
    await events.get()
    second = asyncio.create_task(client.request("hold", {"data": 2}))
    await events.get()
    await client.request("release")
    assert (await first)["data"] == 1
    assert (await second)["data"] == 2
    await client.request("duplicate")
    await client.request("echo")  # Barrier: duplicate and unknown responses were read.
    assert events.empty()


@pytest.mark.asyncio
async def test_failed_void_response(transport: Any) -> None:
    client, _, _ = transport
    with pytest.raises(PiCommandError) as caught:
        await client.request("fail")
    assert caught.value.error == "synthetic failure"
    assert client.running


@pytest.mark.asyncio
async def test_timeout_and_cancel_abandon_only_their_response(transport: Any) -> None:
    client, events, _ = transport
    pending = asyncio.create_task(client.request("hold", timeout=0.05))
    await events.get()
    with pytest.raises(PiTimeoutError) as caught:
        await pending
    assert caught.value.uncertain
    abandoned = asyncio.create_task(client.request("hold"))
    await events.get()
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned
    await client.request("release")
    assert (await client.request("echo", {"data": "next"}))["data"] == "next"
    assert events.empty()


@pytest.mark.asyncio
async def test_final_complete_record_without_lf(transport: Any) -> None:
    client, _, _ = transport
    assert (await client.request("eof"))["success"]
    await client.aclose()
    assert not client.running
    assert client._process.returncode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b"{\n",
        b"[]\n",
        b"{}\n",
        b"\xff\n",
        b'{"type":NaN}\n',
        b'{"type": "response", "success": true}\n',
    ],
)
async def test_malformed_wire_rejects_pending_and_reaps(transport: Any, raw: bytes) -> None:
    client, _, failures = transport
    with pytest.raises(PiProtocolError):
        await client.request("raw", {"hex": raw.hex()})
    await client.aclose()
    assert len(failures) == 1
    assert client._process.returncode is not None


@pytest.mark.asyncio
async def test_truncated_final_json_is_protocol_failure(transport: Any) -> None:
    client, _, _ = transport
    with pytest.raises(PiProtocolError):
        await client.request("raw", {"hex": b'{"type":'.hex(), "exit": True})


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["mismatch", "uncorrelated"])
async def test_invalid_response_correlation_is_fatal(transport: Any, command: str) -> None:
    client, _, _ = transport
    with pytest.raises(PiProtocolError):
        await client.request(command)
    assert not client.running


@pytest.mark.asyncio
async def test_exit_wakes_all_pending(transport: Any) -> None:
    client, events, _ = transport
    pending = asyncio.create_task(client.request("hold"))
    await events.get()
    with pytest.raises(PiProcessError):
        await client.request("exit")
    with pytest.raises(PiProcessError):
        await pending
    await client.aclose()
    await client.aclose()
    assert client._process.returncode == 0


@pytest.mark.asyncio
async def test_ui_reply_uses_original_id_without_response_wait(transport: Any) -> None:
    client, events, _ = transport
    reply = {"type": "extension_ui_response", "id": "dialog-1", "cancelled": True}
    await client.send_ui(reply)
    assert (await events.get())["reply"] == reply
    with pytest.raises(ValueError):
        await client.request("echo", {"id": "replacement"})


@pytest.mark.asyncio
async def test_stderr_retention_is_bounded_and_opt_in(transport: Any) -> None:
    client, _, _ = transport
    await client.request("stderr", {"data": "private synthetic diagnostics"})
    await client.aclose()
    assert client.stderr_tail == ""
    retained = Transport(
        limits=Limits(stderr_tail_bytes=5), on_event=lambda _: None, on_failure=lambda _: None
    )
    await retained.start([sys.executable, FAKE])
    try:
        await retained.request("stderr", {"data": "0123456789"})
    finally:
        await retained.aclose()
    assert retained.stderr_tail == "56789"


@pytest.mark.asyncio
@pytest.mark.parametrize("newline", [True, False])
async def test_oversized_record_is_fatal(newline: bool) -> None:
    client = Transport(
        limits=Limits(max_record_bytes=256), on_event=lambda _: None, on_failure=lambda _: None
    )
    suffix = b"\n" if newline else b""
    await client.start(
        [
            sys.executable,
            "-c",
            f"import sys; sys.stdout.buffer.write(b'x'*257 + {suffix!r}); "
            "sys.stdout.flush(); sys.stdin.read()",
        ]
    )
    try:
        with pytest.raises(PiProtocolError, match="exceeds"):
            await client.request("echo")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_blocked_write_tears_down_uncertain_child() -> None:
    client = Transport(
        limits=Limits(command_timeout=0.1, cleanup_timeout=0.1),
        on_event=lambda _: None,
        on_failure=lambda _: None,
    )
    await client.start([sys.executable, FAKE])
    try:
        await client.request("stop_reading")
        with pytest.raises(PiTimeoutError) as caught:
            await client.request("echo", {"data": "x" * 2_000_000})
        assert caught.value.uncertain
        await client.aclose()
        assert client._process.returncode is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_executable_reports_failure_and_close_is_safe() -> None:
    failures: list[Exception] = []
    client = Transport(limits=Limits(), on_event=lambda _: None, on_failure=failures.append)
    with pytest.raises(PiProcessError):
        await client.start(["a-pi-executable-that-does-not-exist"])
    await client.aclose()
    assert len(failures) == 1


@pytest.mark.asyncio
async def test_cancel_during_write_closes_and_reaps(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Transport(
        limits=Limits(cleanup_timeout=0.1), on_event=lambda _: None, on_failure=lambda _: None
    )
    await client.start([sys.executable, FAKE])
    await client.request("stop_reading")
    assert client._process is not None and client._process.stdin is not None
    entered = asyncio.Event()
    real_drain = client._process.stdin.drain

    async def observed_drain() -> None:
        entered.set()
        await real_drain()

    monkeypatch.setattr(client._process.stdin, "drain", observed_drain)
    pending = asyncio.create_task(client.request("echo", {"data": "x" * 2_000_000}))
    try:
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await client.aclose()
        assert client._process.returncode is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_close_and_cancel_during_spawn_reap_created_child(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    real_spawn = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    release = asyncio.Event()
    children: list[asyncio.subprocess.Process] = []

    async def delayed_spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await real_spawn(*args, **kwargs)
        children.append(process)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    client = Transport(limits=Limits(), on_event=lambda _: None, on_failure=lambda _: None)
    starting = asyncio.create_task(client.start([sys.executable, FAKE]))
    await spawned.wait()
    closing = None
    if cancel:
        starting.cancel()
    else:
        closing = asyncio.create_task(client.aclose())
    release.set()
    with pytest.raises(asyncio.CancelledError if cancel else PiProcessError):
        await starting
    if closing is not None:
        await closing
    assert len(children) == 1
    assert children[0].returncode is not None
    assert not client.running


@pytest.mark.asyncio
async def test_protocol_failure_still_drains_a_flooding_child() -> None:
    client = Transport(
        limits=Limits(cleanup_timeout=0.1), on_event=lambda _: None, on_failure=lambda _: None
    )
    await client.start(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdin.buffer.readline(); "
            "sys.stdout.buffer.write(b'bad json\\n' + b'x' * 2000000); "
            "sys.stdout.flush(); sys.stdin.read()",
        ]
    )
    with pytest.raises(PiProtocolError):
        await client.request("echo")
    await asyncio.wait_for(client.aclose(), 3)
    assert client._process is not None and client._process.returncode is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("response_size", [None, 0, 500_000])
async def test_child_exit_is_terminal_even_when_descendant_inherits_pipes(
    tmp_path: Path, response_size: int | None
) -> None:
    release = tmp_path / "release"
    finished = tmp_path / "finished"
    descendant = (
        "import pathlib, sys, time; "
        "release, finished = map(pathlib.Path, sys.argv[1:]); "
        "deadline = time.monotonic() + 10\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "finished.touch()"
    )
    parent = (
        "import json, subprocess, sys; request = json.loads(sys.stdin.buffer.readline()); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], *sys.argv[2:]], "
        "stdin=subprocess.DEVNULL); "
    )
    if response_size is not None:
        parent += (
            "sys.stdout.write(json.dumps({'type': 'response', 'id': request['id'], "
            f"'command': request['type'], 'success': True, 'data': 'x' * {response_size}}})); "
            "sys.stdout.flush()"
        )
    client = Transport(
        limits=Limits(cleanup_timeout=0.1), on_event=lambda _: None, on_failure=lambda _: None
    )
    await client.start([sys.executable, "-c", parent, descendant, str(release), str(finished)])
    try:
        if response_size is None:
            with pytest.raises(PiProcessError) as caught:
                await client.request("echo", timeout=0.5)
            assert caught.value.returncode == 0
        else:
            result = await client.request("echo", timeout=0.5)
            assert result["data"] == "x" * response_size
        await asyncio.wait_for(client.aclose(), 0.5)
        assert not finished.exists(), "Closing the client must not wait for its descendant"
        assert client._process is not None
        assert client._process.returncode == 0
        process_transport = client._process._transport
        assert process_transport.is_closing()
        assert all(process_transport.get_pipe_transport(fd).is_closing() for fd in (0, 1, 2))
    finally:
        release.touch()
        await client.aclose()
        # The descendant writes this only after release, proving we did not kill it.
        async with asyncio.timeout(5):
            while not finished.exists():  # noqa: ASYNC110 - child filesystem coordination
                await asyncio.sleep(0.01)


@pytest.mark.parametrize("close_early", [False, True])
async def test_burst_exit_routes_each_record_once_before_unterminated_response(close_early):
    events = []
    observed = []
    failures = []
    first_event = asyncio.Event()

    def receive(event):
        events.append(event)
        first_event.set()

    transport = Transport(
        limits=Limits(),
        on_event=receive,
        on_failure=failures.append,
        on_output=lambda source, data: observed.append((source, data)),
    )
    await transport.start([sys.executable, FAKE])
    try:
        pending = asyncio.create_task(transport.request("burst_exit"))
        if close_early:
            await asyncio.wait_for(first_event.wait(), 5)
            await transport.aclose()
            with pytest.raises(PiProcessError):
                await pending
        else:
            assert (await pending)["success"]
    finally:
        await transport.aclose()
    assert [event["sequence"] for event in events] == list(range(len(events)))
    if not close_early:
        assert len(events) == 5000
    objects = [data for source, data in observed if source == "rpc"]
    assert len(objects) == 5001
    assert [event["sequence"] for event in objects[:-1]] == list(range(5000))
    assert objects[-1]["command"] == "burst_exit"
    raw = b"".join(data for source, data in observed if source == "stdout")
    assert [json.loads(line) for line in raw.splitlines()] == objects
