"""The blocking Durable facade shares protocol and lifecycle with async."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

from pi_agent import PiProcessError, PiTimeoutError
from pi_agent.durable import AsyncDurableClient, DurableClient

FAKE = str(Path(__file__).with_name("fake_host.py"))


def test_fake_lifecycle_and_loop_thread_rejection() -> None:
    client = DurableClient(None, host_command=[sys.executable, "-u", FAKE])
    assert client._thread is None and not client.running
    with client:
        cid = client.root(thinking_level="off")
        sid = client.submit(cid, "question", request_id="job", when_busy="followUp")
        assert client.wait(sid).status == "done"
        assert client.entries(cid, limit=3)[0]["future"] is True
        assert client.host_pid is not None and client.pi_durable_version == "1.5.2"
        assert client.stderr_tail == ""
        assert client.limits is client._client.limits
        client.abort(cid)

        async def from_loop() -> None:
            with pytest.raises(RuntimeError, match="callbacks"):
                client.root()
            with pytest.raises(RuntimeError, match="callbacks"):
                client.close()

        client._call(from_loop)
    client.close()
    assert client._thread is not None and not client._thread.is_alive()
    with pytest.raises(PiProcessError):
        client.start()


def test_close_after_host_died() -> None:
    client = DurableClient(None, host_command=[sys.executable, "-u", FAKE, "exit"])
    client.start()
    with pytest.raises(PiProcessError):
        client.wait(8)
    client.close()
    client.close()
    assert client._thread is not None and not client._thread.is_alive()


def test_close_before_start() -> None:
    client = DurableClient(None)
    client.close()
    client.close()
    assert client._thread is None


def test_read_timeout_preserves_async_semantics() -> None:
    with DurableClient(None, host_command=[sys.executable, "-u", FAKE, "timeout_wait"]) as client:
        with pytest.raises(PiTimeoutError) as caught:
            client.wait(8, timeout=0.05)
        assert not caught.value.uncertain
        assert client.wait(8, timeout=1).status == "done"


def test_explicit_signatures_match() -> None:
    for method in ["__init__", "root", "submit", "wait", "entries", "abort"]:
        sync = inspect.signature(getattr(DurableClient, method))
        async_ = inspect.signature(getattr(AsyncDurableClient, method))
        assert sync == async_


@pytest.mark.parametrize("sqlite", [False, True])
def test_real_sync_flow(durable_host_command: list[str], tmp_path: Path, sqlite: bool) -> None:
    with DurableClient(
        tmp_path / "state.db" if sqlite else None,
        host_command=durable_host_command,
        cwd=tmp_path,
        inherit_env=False,
        faux=["Synthetic answer"],
    ) as client:
        cid = client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = client.submit(cid, "question", request_id="job")
        assert client.wait(sid, timeout=10).status == "done"
        assert client.submit(cid, "ignored", request_id="job") == sid
        entries = client.entries(cid)
        assert entries[0]["kind"] == "pi.user"
        assert entries[-1]["kind"] == "pi.assistant"
        client.abort(cid)


def test_failed_start_reaps_loop() -> None:
    client = DurableClient(None)
    with pytest.raises(PiProcessError):
        client.start()
    client.close()
    assert client._thread is not None and not client._thread.is_alive()


def test_async_core_never_calls_blocking_facade() -> None:
    # A basic lifecycle on its own loop remains independent of sync use.
    async def run() -> None:
        async with AsyncDurableClient(None, host_command=[sys.executable, "-u", FAKE]) as client:
            assert await client.root() == 1

    asyncio.run(run())
