"""Real SQLite recovery after SIGKILL; no Python or host recovery implementation."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import pytest

from pi_agent.durable import AsyncDurableClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name == "nt", reason="SIGKILL requires POSIX"),
]

ANSWER = " ".join(["word"] * 400)
SETTINGS = {"progress": {"persistWithinMs": 50}, "retry": {"baseDelayMs": 50}}
MODEL = {"provider": "faux", "modelId": "faux-1"}


def client(path: Path, command: list[str]) -> AsyncDurableClient:
    return AsyncDurableClient(
        path,
        host_command=command,
        cwd=path.parent,
        inherit_env=False,
        settings=SETTINGS,
        faux=[ANSWER],
        faux_tokens_per_second=50,
    )


def partial_length(live: dict[str, Any] | None) -> int:
    content = (live or {}).get("generation", {}).get("message", {}).get("content", [])
    return sum(len(block.get("text", "")) for block in content if block.get("type") == "text")


async def test_recovery_host_crash(durable_host_command: list[str], tmp_path: Path) -> None:
    path = tmp_path / "host-crash.db"
    first = client(path, durable_host_command)
    await first.start()
    try:
        cid = await first.root(model=MODEL)
        async with first.watch(cid) as updates:
            sid = await first.submit(cid, "question", request_id="job-42")
            async with asyncio.timeout(30):
                async for update in updates:
                    if partial_length(update.live) >= 200:
                        assert first.host_pid is not None
                        os.kill(first.host_pid, signal.SIGKILL)
                        break
                else:
                    pytest.fail("Watch ended before partial output reached 200 characters")
    finally:
        await first.aclose()
    async with client(path, durable_host_command) as reopened:
        cid = await reopened.root(model=MODEL)
        assert await reopened.submit(cid, "question", request_id="job-42") == sid
        assert (await reopened.wait(sid, timeout=30)).status == "done"
        entries = await reopened.entries(cid)
        assert sum(e["kind"] == "pi.user" for e in entries) == 1
        assistants = [e for e in entries if e["kind"] == "pi.assistant"]
        aborted = sum(e["model"][0]["stopReason"] == "aborted" for e in assistants)
        print(f"Host crash recovered; persisted aborted entries: {aborted}")
        assert aborted <= 1
        assert entries[-1]["kind"] == "pi.assistant"
        assert assistants[-1]["model"][0]["stopReason"] == "stop"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed Python parent's child may be reparented to a container PID 1 that
    # delays reaping. A zombie has exited and no longer holds storage or pipes.
    stat = Path(f"/proc/{pid}/stat")
    try:
        if stat.is_file() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
            return False
    except FileNotFoundError:
        return False
    return True


_CHILD = """
import asyncio, json, sys
from pi_agent.durable import AsyncDurableClient
async def main():
    options = json.loads(sys.argv[1])
    async with AsyncDurableClient(**options) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await client.submit(cid, "question", request_id="job-43")
        print(json.dumps({"host_pid": client.host_pid, "sid": sid}), flush=True)
        await client.wait(sid)
asyncio.run(main())
"""


async def test_recovery_python_crash(durable_host_command: list[str], tmp_path: Path) -> None:
    path = tmp_path / "python-crash.db"
    options = dict(
        storage_path=str(path),
        host_command=durable_host_command,
        cwd=str(tmp_path),
        inherit_env=False,
        settings=SETTINGS,
        faux=[ANSWER],
        faux_tokens_per_second=50,
    )
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        _CHILD,
        json.dumps(options),
        cwd=tmp_path,
        env={},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    host_pid: int | None = None
    try:
        assert child.stdout is not None
        async with asyncio.timeout(30):
            line = await child.stdout.readline()
        assert line, "Synthetic recovery child exited before reporting host PID"
        info = json.loads(line)
        host_pid = info["host_pid"]
        child.kill()
        await child.wait()
        async with asyncio.timeout(30):
            while alive(host_pid):  # noqa: ASYNC110 - explicit bounded process-exit polling
                await asyncio.sleep(0.01)
        async with client(path, durable_host_command) as reopened:
            cid = await reopened.root(model=MODEL)
            sid = await reopened.submit(cid, "question", request_id="job-43")
            assert sid == info["sid"]
            assert (await reopened.wait(sid, timeout=30)).status == "done"
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()
        if host_pid is not None and alive(host_pid):
            os.kill(host_pid, signal.SIGKILL)


async def test_recovery_no_double_submit(durable_host_command: list[str], tmp_path: Path) -> None:
    path = tmp_path / "settled.db"
    async with client(path, durable_host_command) as first:
        cid = await first.root(model=MODEL)
        sid = await first.submit(cid, "question", request_id="settled-key")
        assert (await first.wait(sid, timeout=30)).status == "done"
        before = await first.entries(cid)
    async with client(path, durable_host_command) as reopened:
        assert await reopened.root(model=MODEL) == cid
        assert await reopened.submit(cid, "ignored", request_id="settled-key") == sid
        assert (await reopened.wait(sid, timeout=30)).status == "done"
        after = await reopened.entries(cid)
        assert after == before
        assert sum(e["kind"] == "pi.user" for e in after) == 1
