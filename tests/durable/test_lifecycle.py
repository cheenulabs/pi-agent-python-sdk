"""Shutdown and working-directory regressions from the independent review."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import Limits
from pi_agent.durable import AsyncDurableClient, WatchUpdate

FAKE = str(Path(__file__).with_name("fake_host.py"))


async def test_cancelled_close_still_reaps_host_with_pending_unwatch() -> None:
    client = AsyncDurableClient(
        None,
        host_command=[sys.executable, "-u", FAKE, "timeout_unwatch"],
        limits=Limits(cleanup_timeout=5),
    )
    await client.start()
    assert client._transport is not None and client._transport._process is not None
    process = client._transport._process
    subscription_close: asyncio.Task[None] | None = None
    try:
        subscription = client.watch(1)
        await subscription.__aenter__()
        await anext(subscription)
        subscription_close = asyncio.create_task(subscription.aclose())
        await asyncio.sleep(0)  # Schedule cleanup, then use a peer barrier rather than a delay.
        await client.root()
        assert any(not task.done() for task in client._background)
        closing = asyncio.create_task(client.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        async with asyncio.timeout(5):
            while process.returncode is None:  # noqa: ASYNC110 - bounded actual child-exit polling
                await asyncio.sleep(0.01)
        assert process.returncode == 0
        await client.aclose()
        await client.aclose()
        assert not client.running and not client._background
    finally:
        await client.aclose()
        if subscription_close is not None:
            await asyncio.gather(subscription_close, return_exceptions=True)


async def test_close_joins_startup_not_application_finally() -> None:
    client = AsyncDurableClient(None, host_command=[sys.executable, "-u", FAKE, "startup_timeout"])
    in_application_finally = asyncio.Event()
    close_returned = asyncio.Event()

    async def application() -> None:
        try:
            await client.start()
        finally:
            in_application_finally.set()
            await close_returned.wait()

    starting = asyncio.create_task(application())
    closing: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(5):
            while client._transport is None or not client._transport.running:  # noqa: ASYNC110 - bounded startup polling
                await asyncio.sleep(0)
        process = client._transport._process
        assert process is not None
        closing = asyncio.create_task(client.aclose())
        async with asyncio.timeout(5):
            await closing
        assert in_application_finally.is_set() and not starting.done()
        assert process.returncode is not None
        close_returned.set()
        await asyncio.gather(starting, return_exceptions=True)
    finally:
        close_returned.set()
        await asyncio.gather(starting, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await client.aclose()


async def test_relative_constructor_cwd_applies_once(
    durable_host_command: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "project").mkdir()
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        cwd="project",
        inherit_env=False,
        faux=[{"tool": "write", "args": {"path": "result.txt", "content": "synthetic"}}, "done"],
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await client.submit(cid, "Synthetic file write", request_id="relative-cwd")
        assert (await client.wait(sid, timeout=10)).status == "done"
    assert (tmp_path / "project/result.txt").read_text() == "synthetic"
    assert not (tmp_path / "project/project").exists()


def test_watch_repr_omits_conversation_and_live_payloads() -> None:
    marker = "synthetic-private-text"
    update = WatchUpdate(
        entries=[{"content": marker}],
        live={"generation": {"text": marker}},
        gap=False,
        snapshot=True,
        raw={"future": marker},
    )
    assert marker not in repr(update)
    assert "entries=" not in repr(update) and "live=" not in repr(update)
    assert update.entries[0]["content"] == marker
    assert update.live == {"generation": {"text": marker}}
