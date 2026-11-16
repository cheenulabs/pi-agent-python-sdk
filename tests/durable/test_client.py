"""Public async Durable behavior, fake-host failures and real Harness integration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import (
    Limits,
    PiCommandError,
    PiProcessError,
    PiProtocolError,
    PiTimeoutError,
    PiVersionError,
)
from pi_agent.durable import AsyncDurableClient

FAKE = str(Path(__file__).with_name("fake_host.py"))


def fake(mode: str = "normal", **kwargs: object) -> AsyncDurableClient:
    return AsyncDurableClient(None, host_command=[sys.executable, "-u", FAKE, mode], **kwargs)  # type: ignore[arg-type]


async def test_fake_flow_and_unknown_fields() -> None:
    client = fake()
    assert not client.running and client.host_pid is None and client.pi_durable_version is None
    async with client:
        assert client.running and client.host_pid is not None
        assert client.pi_durable_version == "1.5.2"
        cid = await client.root()
        sid = await client.submit(cid, "question", request_id="job")
        result = await client.wait(sid)
        assert result.status == "done" and result.reason is None
        assert result.raw["future"] == {"retained": True}
        assert (await client.entries(cid))[0]["future"] is True
        await client.abort(cid)
        with pytest.raises(ValueError):
            await client.submit(cid, "question", request_id="")
    assert not client.running
    await client.aclose()
    with pytest.raises(PiProcessError):
        await client.start()


@pytest.mark.parametrize("command", [None, ["pi-durable-missing-synthetic-program"]])
async def test_missing_host(command: list[str] | None) -> None:
    client = AsyncDurableClient(None, host_command=command)
    with pytest.raises(PiProcessError, match="Node >=22.19.*host_command"):
        await client.start()
    await client.aclose()


@pytest.mark.parametrize("capacity", [0, 512])
async def test_missing_host_script_has_safe_startup_hint(tmp_path: Path, capacity: int) -> None:
    missing = tmp_path / "synthetic-missing-host.py"
    client = AsyncDurableClient(
        None,
        host_command=[sys.executable, str(missing)],
        limits=Limits(stderr_tail_bytes=capacity),
    )
    with pytest.raises(PiProcessError) as caught:
        await client.start()
    message = str(caught.value)
    assert "Durable host exited during startup" in message
    assert "host_command" in message and "npm ci --prefix host" in message
    assert "Limits(stderr_tail_bytes=" in message
    assert str(missing) not in message
    assert "can't open file" not in message
    assert bool(client.stderr_tail) is bool(capacity)
    assert not client.running
    await client.aclose()


async def test_protocol_mismatch() -> None:
    client = fake("protocol")
    with pytest.raises(PiVersionError):
        await client.start()
    assert not client.running
    await client.aclose()


async def test_startup_timeout() -> None:
    client = fake("startup_timeout", limits=Limits(startup_timeout=0.1))
    with pytest.raises(PiTimeoutError) as caught:
        await client.start()
    assert not caught.value.uncertain
    await client.aclose()


async def test_startup_cancellation_and_concurrent_close() -> None:
    client = fake("startup_timeout")
    pending = asyncio.create_task(client.start())
    async with asyncio.timeout(5):
        while client._transport is None:  # noqa: ASYNC110 - bounded startup polling
            await asyncio.sleep(0)
        await client.aclose()
    assert pending.cancelled()
    assert not client.running


async def test_error_code() -> None:
    async with fake("error") as client:
        with pytest.raises(PiCommandError) as caught:
            await client.abort(1)
        assert caught.value.code == "not_found"
        assert caught.value.error == "synthetic-private-error"
        assert "synthetic-private" not in str(caught.value)


async def test_host_exit_and_close() -> None:
    client = fake("exit")
    await client.start()
    with pytest.raises(PiProcessError):
        await client.wait(8)
    await client.aclose()
    await client.aclose()


@pytest.mark.parametrize(
    "command,uncertain", [("wait", False), ("submit", True), ("entries", False)]
)
async def test_response_timeout_is_local(command: str, uncertain: bool) -> None:
    async with fake("timeout_" + command) as client:

        async def invoke(timeout: float | None) -> object:
            if command == "wait":
                return await client.wait(8, timeout=timeout)
            if command == "entries":
                return await client.entries(1, timeout=timeout)
            return await client.submit(1, "question", request_id="job", timeout=timeout)

        with pytest.raises(PiTimeoutError) as caught:
            await invoke(0.05)
        assert caught.value.uncertain is uncertain
        assert caught.value.command == command
        assert await invoke(1) is not None
        assert client.running


@pytest.mark.parametrize("command", ["hello", "open", "root", "submit", "wait", "entries", "abort"])
async def test_wrong_data(command: str) -> None:
    client = fake("wrong_" + command)
    try:
        with pytest.raises(PiProtocolError):
            await client.start()
            if command == "root":
                await client.root()
            elif command == "submit":
                await client.submit(1, "question", request_id="job")
            elif command == "wait":
                await client.wait(8)
            elif command == "entries":
                await client.entries(1)
            elif command == "abort":
                await client.abort(1)
    finally:
        await client.aclose()


@pytest.mark.parametrize("capacity", [0, 32])
async def test_stderr_is_opt_in_bounded_and_not_in_exceptions(capacity: int) -> None:
    async with fake("stderr", limits=Limits(stderr_tail_bytes=capacity)) as client:
        if capacity:
            async with asyncio.timeout(5):
                while not client.stderr_tail:  # noqa: ASYNC110 - bounded pipe-drain polling
                    await asyncio.sleep(0)
        assert len(client.stderr_tail.encode()) <= capacity
        with pytest.raises(PiCommandError) as caught:
            await client.abort(1)
        assert "synthetic-private" not in str(caught.value)
    assert len(client.stderr_tail.encode()) <= capacity


@pytest.mark.parametrize("sqlite", [False, True])
async def test_real_flow(durable_host_command: list[str], tmp_path: Path, sqlite: bool) -> None:
    async with AsyncDurableClient(
        tmp_path / "state.db" if sqlite else None,
        host_command=durable_host_command,
        cwd=tmp_path,
        inherit_env=False,
        faux=["Synthetic answer"],
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await client.submit(cid, "question", request_id="job")
        assert (await client.wait(sid, timeout=10)).status == "done"
        assert await client.submit(cid, "ignored", request_id="job") == sid
        entries = await client.entries(cid)
        assert entries[0]["kind"] == "pi.user"
        assert entries[-1]["kind"] == "pi.assistant"
        await client.abort(cid)
