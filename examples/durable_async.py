"""Async Durable submit/wait/answer flow with a faux model and temporary SQLite.

Run npm ci --prefix durable-host first. No provider credentials are needed.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from pi_agent.durable import AsyncDurableClient


def host_command() -> list[str]:
    return [
        shutil.which("node") or "node",
        str(Path(__file__).resolve().parents[1] / "durable-host/src/host.ts"),
    ]


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pi-durable-async-example-") as temporary:
        async with AsyncDurableClient(
            Path(temporary) / "state.db",
            host_command=host_command(),
            cwd=temporary,
            inherit_env=False,
            faux=["Hello from async Durable."],
        ) as durable:
            cid = await durable.root(model={"provider": "faux", "modelId": "faux-1"})
            sid = await durable.submit(cid, "Hello", request_id="async-job-1")
            settled = await durable.wait(sid, timeout=30)
            text = await durable.answer_text(settled)
            assert settled.status == "done" and text is not None
            print(text)


if __name__ == "__main__":
    asyncio.run(main())
