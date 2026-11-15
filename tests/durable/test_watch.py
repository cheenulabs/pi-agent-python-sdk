"""Watch snapshots, streaming, cleanup and bounded loss with synthetic data."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from pi_agent import Limits, PiCommandError, PiProcessError, PiSubscriptionOverflow, PiTimeoutError
from pi_agent.durable import AsyncDurableClient, DurableClient

from .test_host import running_host

FAKE = str(Path(__file__).with_name("fake_host.py"))


def fake(mode: str = "normal", limits: Limits | None = None) -> AsyncDurableClient:
    return AsyncDurableClient(None, host_command=[sys.executable, "-u", FAKE, mode], limits=limits)


async def test_host_watch_validation_and_ack_order(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.error("watch", "not_open", conversationId=1, watchId="w")
        await host.ok("open", storage={"kind": "memory"}, faux=["answer"])
        cid = (await host.ok("root"))["conversationId"]
        await host.error("watch", "bad_params", conversationId=cid)
        await host.error("watch", "not_found", conversationId=999999, watchId="missing")
        await host.ok("watch", conversationId=cid, watchId="w")
        snapshot = await host.record()
        assert snapshot["type"] == "durable_watch" and snapshot["snapshot"] is True
        assert snapshot["watchId"] == "w" and snapshot["gap"] is False
        await host.error("watch", "bad_params", conversationId=cid, watchId="w")
        await host.ok("unwatch", watchId="w")
        await host.ok("unwatch", watchId="w")
        await host.ok("watch", conversationId=cid, watchId="w")
        assert (await host.record())["snapshot"] is True
        assert (await host.eof())[0] == 0


async def test_snapshot_raw_and_context_exit_unwatches() -> None:
    async with fake() as client:
        async with client.watch(1) as updates:
            first = await anext(updates)
            assert first.snapshot and not first.gap and first.raw["future"] is True
            watch_id = updates._watch_id
        assert not client._watches
        assert watch_id in (await client.entries(1))[0]["unwatched"]


async def test_watch_end_stops_iteration() -> None:
    async with fake("watch_end") as client:
        async with client.watch(1) as updates:
            assert (await anext(updates)).snapshot
            with pytest.raises(StopAsyncIteration):
                await anext(updates)


async def test_failure_finishes_watch() -> None:
    async with fake("exit") as client:
        async with client.watch(1) as updates:
            await anext(updates)
            with pytest.raises(PiProcessError):
                await client.wait(8)
            with pytest.raises(PiProcessError):
                await anext(updates)


async def test_overflow_unwatches_and_reenter_works() -> None:
    async with fake("burst", Limits(event_queue_size=1)) as client:
        for _ in range(2):
            async with client.watch(1) as updates:
                await client.entries(1)  # Barrier: burst has been read before response.
                with pytest.raises(PiSubscriptionOverflow):
                    await anext(updates)
            assert not client._watches
        assert len((await client.entries(1))[0]["unwatched"]) == 2


@pytest.mark.parametrize("mode", ["watch_error", "timeout_watch"])
async def test_failed_watch_unregisters_and_cleans_up(mode: str) -> None:
    async with fake(mode, Limits(command_timeout=0.1)) as client:
        updates = client.watch(1)
        with pytest.raises((PiCommandError, PiTimeoutError)):
            await updates.__aenter__()
        await asyncio.gather(*client._background)
        assert not client._watches
        assert updates._watch_id in (await client.entries(1))[0]["unwatched"]


async def test_cancelled_watch_cleanup_is_tracked() -> None:
    async with fake("timeout_watch") as client:
        updates = client.watch(1)
        pending = asyncio.create_task(updates.__aenter__())
        # Root response is a peer barrier after the watch write, without fixed sleeps.
        await client.root()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.gather(*client._background)
        assert not client._watches
        assert updates._watch_id in (await client.entries(1))[0]["unwatched"]


def test_sync_watch() -> None:
    with DurableClient(None, host_command=[sys.executable, "-u", FAKE, "watch_end"]) as client:
        with client.watch(1) as updates:
            records = list(updates)
        assert len(records) == 1 and records[0].snapshot


async def test_real_snapshot_and_exactly_once_entries(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        cwd=tmp_path,
        inherit_env=False,
        faux=["Synthetic streamed answer"],
        faux_tokens_per_second=100,
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        async with client.watch(cid) as updates:
            first = await anext(updates)
            assert first.snapshot and not first.gap
            received = list(first.entries)
            sid = await client.submit(cid, "question", request_id="watch-1")
            async with asyncio.timeout(10):
                async for update in updates:
                    assert not update.snapshot and not update.gap
                    received.extend(update.entries)
                    if (
                        received
                        and received[-1]["kind"] == "pi.assistant"
                        and not (update.live and update.live.get("generation"))
                    ):
                        break
            assert (await client.wait(sid, timeout=10)).status == "done"
            entries = await client.entries(cid)
            assert [e["id"] for e in received] == [e["id"] for e in entries]
            assert len({e["id"] for e in received}) == len(received)
        async with client.watch(cid) as again:
            snapshot = await anext(again)
            assert snapshot.snapshot and not snapshot.gap
            assert snapshot.entries == entries


async def test_real_oversized_snapshot_and_later_event(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    # Enough room for commands and gap replacement, not a large transcript/live view.
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        cwd=tmp_path,
        inherit_env=False,
        limits=Limits(max_record_bytes=2048),
        faux=["large " * 200, "short"],
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        async with client.watch(cid) as updates:
            assert (await anext(updates)).snapshot
            sid = await client.submit(cid, "question", request_id="large")
            async with asyncio.timeout(10):
                while True:
                    update = await anext(updates)
                    if update.gap:
                        assert not update.snapshot
                        assert update.entries == [] and update.live is None
                        break
            await client.wait(sid, timeout=10)
            await client.root()  # Peer barrier after the settled commit.
            while updates._records:
                await anext(updates)
            # On this same watch, skipped IDs must not recur in the next run.
            sid = await client.submit(cid, "short question", request_id="after-gap")
            async with asyncio.timeout(10):
                async for update in updates:
                    assert not update.gap
                    assert all("large large" not in str(e) for e in update.entries)
                    if (
                        update.entries
                        and update.entries[-1]["kind"] == "pi.assistant"
                        and not (update.live and update.live.get("generation"))
                    ):
                        break
            await client.wait(sid, timeout=10)
        async with client.watch(cid) as updates:
            snapshot = await anext(updates)
            assert (
                snapshot.snapshot
                and snapshot.gap
                and snapshot.entries == []
                and snapshot.live is None
            )
        # Snapshot skipped entries must not be repeated on a later update of that watch.
        async with client.watch(cid) as updates:
            assert (await anext(updates)).gap
            sid = await client.submit(cid, "next", request_id="short")
            received: list[int] = []
            async with asyncio.timeout(10):
                async for update in updates:
                    received.extend(e["id"] for e in update.entries)
                    if (
                        update.entries
                        and update.entries[-1]["kind"] == "pi.assistant"
                        and not (update.live and update.live.get("generation"))
                    ):
                        break
            await client.wait(sid, timeout=10)
            newest = await client.entries(cid, limit=1)
            assert newest[0]["id"] in received
            assert len(set(received)) == len(received)
            assert all(e["id"] in received for e in await client.entries(cid, limit=2))
