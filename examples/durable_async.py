"""Async Durable submit/wait/answer flow with a faux model and temporary SQLite.

Run npm ci --prefix durable-host first. No provider credentials are needed.
PI_DURABLE_HOST may override the file-relative host with a JSON argv array.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from pi_agent.durable import AsyncDurableClient


def host_command() -> list[str]:
    configured = os.environ.get("PI_DURABLE_HOST")
    if configured is None:
        return ["node", str(Path(__file__).resolve().parents[1] / "durable-host/src/host.ts")]
    value = json.loads(configured)
    if not isinstance(value, list) or not value or any(not isinstance(arg, str) for arg in value):
        raise ValueError("PI_DURABLE_HOST must be a non-empty JSON argv array")
    return value


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pi-durable-async-example-") as temporary:
        async with AsyncDurableClient(
            Path(temporary) / "state.db",
            host_command=host_command(),
            cwd=temporary,
            inherit_env=False,
            env={"PATH": os.environ.get("PATH", os.defpath)},
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
