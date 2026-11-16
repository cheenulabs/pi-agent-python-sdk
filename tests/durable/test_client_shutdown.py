"""The default Durable grace reaches owned cleanup before transport escalation."""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path

import pytest

from pi_agent import Limits
from pi_agent.durable import AsyncDurableClient

from .test_host import fault_command


def instrumented(command: list[str], directory: Path, *, hang: bool) -> list[str]:
    package = (
        Path(command[1]).parents[1] / "node_modules/@earendil-works/pi-coding-agent/dist/index.js"
    )
    script = f"""
import {{ModelRuntime}} from {json.dumps(package.as_uri())};
import {{appendFileSync, writeFileSync}} from 'node:fs';
const create = ModelRuntime.create;
ModelRuntime.create = async (...args) => {{
  const runtime = await create(...args);
  const settle = runtime.settleCredentialWrites.bind(runtime);
  runtime.settleCredentialWrites = async () => {{
    appendFileSync({json.dumps(str(directory / "settle-count"))}, '1');
    await settle();
    writeFileSync({json.dumps(str(directory / "settled"))}, '1');
  }};
  return runtime;
}};
if ({str(hang).lower()}) {{
  const open = Harness.open;
  Harness.open = async (...args) => {{
    const harness = await open(...args);
    harness.close = async () => new Promise(() => {{}});
    return harness;
  }};
}}
"""
    return fault_command(command, directory, script)


def test_durable_default_grace_does_not_change_core_limits() -> None:
    assert Limits().cleanup_timeout == 5
    assert AsyncDurableClient(None).limits.cleanup_timeout == 25
    explicit = Limits(cleanup_timeout=1)
    assert AsyncDurableClient(None, limits=explicit).limits is explicit


async def test_default_client_close_settles_after_hung_harness(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    client = AsyncDurableClient(
        None,
        host_command=instrumented(durable_host_command, tmp_path, hang=True),
        cwd=tmp_path,
        pi_agent_dir=tmp_path,
        inherit_env=False,
        env={"HOME": str(tmp_path), "PI_OFFLINE": "1", "AWS_EC2_METADATA_DISABLED": "true"},
    )
    try:
        await client.start()
        assert client.limits.cleanup_timeout == 25
        assert client._transport is not None and client._transport._process is not None
        process = client._transport._process
        async with asyncio.timeout(30):
            await client.aclose()
        assert process.returncode == 1
        assert not client.running
        assert (tmp_path / "settled").exists()
        assert (tmp_path / "settle-count").read_text() == "1"
    finally:
        await client.aclose()


@pytest.mark.skipif(sys.platform == "win32", reason="Durable signal handling is POSIX-only")
async def test_signals_preserve_owned_cleanup(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    client = AsyncDurableClient(
        None,
        host_command=instrumented(durable_host_command, tmp_path, hang=False),
        cwd=tmp_path,
        pi_agent_dir=tmp_path,
        inherit_env=False,
        env={"HOME": str(tmp_path), "PI_OFFLINE": "1", "AWS_EC2_METADATA_DISABLED": "true"},
    )
    try:
        await client.start()
        assert client._transport is not None and client._transport._process is not None
        process = client._transport._process
        process.send_signal(signal.SIGINT)
        await client.root(timeout=10)  # SIGINT must not terminate the child.
        process.send_signal(signal.SIGTERM)
        async with asyncio.timeout(30):
            await process.wait()
        assert process.returncode == 1
        assert (tmp_path / "settled").exists()
        assert (tmp_path / "settle-count").read_text() == "1"
    finally:
        await client.aclose()
