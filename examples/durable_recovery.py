"""Recover a faux submission after killing the host; Linux/macOS, no keys needed.

Install the checkout's host dependencies first: npm ci --prefix host.
PI_DURABLE_HOST may contain a JSON argv array, e.g. ["node", "/path/host.ts"].
The default host path is resolved relative to this file, never the caller's cwd.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from pathlib import Path

from pi_agent.durable import AsyncDurableClient


def host_command() -> list[str]:
    configured = os.environ.get("PI_DURABLE_HOST")
    if configured is None:
        return ["node", str(Path(__file__).resolve().parents[1] / "host/src/host.ts")]
    value = json.loads(configured)
    if not isinstance(value, list) or not value or any(not isinstance(arg, str) for arg in value):
        raise ValueError("PI_DURABLE_HOST must be a non-empty JSON argv array")
    return value


async def main() -> None:
    if os.name == "nt":
        raise RuntimeError("Pi Durable v0 and this SIGKILL example support Linux/macOS only")
    command = host_command()
    answer = " ".join(["Synthetic recovery answer."] * 100)
    with tempfile.TemporaryDirectory(prefix="pi-durable-example-") as temporary:
        path = Path(temporary) / "state.db"

        def client() -> AsyncDurableClient:
            return AsyncDurableClient(
                path,
                host_command=command,
                cwd=temporary,
                inherit_env=False,
                env={"PATH": os.environ.get("PATH", os.defpath)},
                settings={"progress": {"persistWithinMs": 50}, "retry": {"baseDelayMs": 50}},
                faux=[answer],
                faux_tokens_per_second=200,
            )

        async with client() as first:
            cid = await first.root(model={"provider": "faux", "modelId": "faux-1"})
            async with first.watch(cid) as updates:
                sid = await first.submit(cid, "Synthetic question", request_id="example-job")
                async with asyncio.timeout(30):
                    async for update in updates:
                        generation = (update.live or {}).get("generation") or {}
                        content = (generation.get("message") or {}).get("content", [])
                        text = "".join(
                            b.get("text", "") for b in content if b.get("type") == "text"
                        )
                        if len(text) >= 200:
                            assert first.host_pid is not None
                            os.kill(first.host_pid, signal.SIGKILL)
                            break
                    else:
                        raise RuntimeError("Host ended before producing partial output")

        # A new client, same file, same conversation and request key: no replay
        # implementation here. Harness.open/resume owns upstream recovery.
        async with client() as reopened:
            cid = await reopened.root()
            recovered = await reopened.submit(cid, "Synthetic question", request_id="example-job")
            assert recovered == sid
            settled = await reopened.wait(recovered, timeout=30)
            entries = await reopened.entries(cid)
            users = sum(entry["kind"] == "pi.user" for entry in entries)
            assert settled.status == "done" and users == 1
            print(f"Recovered submission {recovered}: {settled.status}; user entries: {users}")


if __name__ == "__main__":
    asyncio.run(main())
