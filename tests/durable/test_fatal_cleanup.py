"""Owned cleanup must join synthetic persistence on EOF and deliberate fatal exits."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from .test_host import fault_command, running_host


@pytest.mark.parametrize(
    "mode",
    [
        "eof",
        "serialization",
        "tiny_limit",
        "watch_limit",
        "write_failure",
        "stream_error",
        "fatal_open",
        "hung_close",
        "hung_settle",
    ],
)
async def test_owned_exit_persistence(
    durable_host_command: list[str], tmp_path: Path, mode: str
) -> None:
    package = (
        Path(durable_host_command[1]).parents[1]
        / "node_modules/@earendil-works/pi-coding-agent/dist/index.js"
    )
    script = f"""
import {{ModelRuntime}} from {json.dumps(package.as_uri())};
import {{writeFileSync, appendFileSync}} from 'node:fs';
const mode = {json.dumps(mode)};
const directory = {json.dumps(str(tmp_path))};
let pending = Promise.resolve();
function queuePersistence() {{
  pending = new Promise(resolve => setTimeout(() => {{
    writeFileSync(directory + '/persisted', 'synthetic'); resolve();
  }}, 200));
}}
const create = ModelRuntime.create;
ModelRuntime.create = async (...args) => {{
  const runtime = await create(...args);
  const settle = runtime.settleCredentialWrites.bind(runtime);
  runtime.settleCredentialWrites = async () => {{
    writeFileSync(directory + '/settle-started', '1');
    if (mode === 'hung_settle') await new Promise(() => {{}});
    await pending;
    await settle();
    writeFileSync(directory + '/settled', '1');
  }};
  return runtime;
}};
const open = Harness.open;
Harness.open = async (...args) => {{
  const harness = await open(...args);
  queuePersistence();
  const close = harness.close.bind(harness);
  harness.close = async (...closeArgs) => {{
    appendFileSync(directory + '/close-attempts', '1');
    if (mode === 'hung_close') await new Promise(() => {{}});
    await close(...closeArgs);
    writeFileSync(directory + '/closed', '1');
  }};
  if (['serialization', 'hung_close', 'hung_settle'].includes(mode))
    harness.root = async () => ({{id: 1n}});
  if (mode === 'stream_error') harness.root = async () => {{
    process.stdout.emit('error', Object.assign(
      new Error('synthetic stream failure'), {{code: 'EIO'}}));
    return {{id: 1}};
  }};
  if (mode === 'fatal_open') {{
    process.stdout.emit('error', Object.assign(
      new Error('synthetic opening failure'), {{code: 'EIO'}}));
    await new Promise(resolve => setTimeout(resolve, 20));
  }}
  return harness;
}};
if (mode === 'write_failure') {{
  const write = process.stdout.write.bind(process.stdout);
  process.stdout.write = (chunk, ...args) => {{
    if (String(chunk).includes('"command":"root"')) throw new Error('synthetic write failure');
    return write(chunk, ...args);
  }};
}}
"""
    command = fault_command(durable_host_command, tmp_path, script)
    async with running_host(command, tmp_path) as host:
        opening = {
            "id": "open",
            "type": "open",
            "storage": {"kind": "memory"},
            "piAgentDir": str(tmp_path),
        }
        if mode == "tiny_limit":
            opening["maxRecordBytes"] = 1
        elif mode == "watch_limit":
            opening["maxRecordBytes"] = 256
        start = time.monotonic()
        await host.send(opening)
        if mode not in {"tiny_limit", "fatal_open"}:
            assert (await host.response(opening))["success"]
            start = time.monotonic()  # Measure shutdown, not model-runtime startup.
            if mode == "eof":
                assert host.process.stdin is not None
                host.process.stdin.close()
            elif mode == "watch_limit":
                cid = (await host.ok("root"))["conversationId"]
                await host.send(
                    {"id": "watch", "type": "watch", "conversationId": cid, "watchId": "x" * 1000}
                )
            else:
                await host.send({"id": "root", "type": "root"})
        assert host.process.stdout is not None
        async with asyncio.timeout(26):
            await host.process.stdout.read()
            code = await host.process.wait()
        elapsed = time.monotonic() - start
        assert (code == 0) == (mode == "eof")
        assert (tmp_path / "close-attempts").read_text() == "1"
        assert (tmp_path / "settle-started").exists()
        assert (tmp_path / "persisted").exists()
        if mode == "hung_settle":
            assert not (tmp_path / "settled").exists()
            assert 19 <= elapsed < 25
        else:
            assert (tmp_path / "settled").exists()
        assert (tmp_path / "closed").exists() == (mode != "hung_close")
