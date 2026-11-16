"""Exercise upstream Pi configuration with synthetic keys and loopback HTTP only."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from pi_agent import Limits, PiCommandError
from pi_agent._transport import Transport
from pi_agent.durable import AsyncDurableClient, DurableClient

SECRET = "synthetic-pi-sdk-test-key-not-a-real-credential"
ANSWER = "Local configured model answer."


@pytest.mark.parametrize("mode", ["default", "pi", "builtin"])
@pytest.mark.parametrize("directory", ["explicit", "environment"])
@pytest.mark.parametrize("credential", ["stored", "config"])
async def test_pi_model_configuration(
    durable_host_command: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    directory: str,
    credential: str,
) -> None:
    calls: list[dict[str, Any]] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(10):
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode().split("\r\n")
                headers = {
                    key.lower(): value
                    for key, value in (line.split(": ", 1) for line in lines[1:] if ": " in line)
                }
                body = await reader.readexactly(int(headers.get("content-length", "0")))
                calls.append({"request": lines[0], "headers": headers, "body": json.loads(body)})
                chunks = [
                    {
                        "id": "local",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "stub",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": ANSWER},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "local",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "stub",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ]
                payload = (
                    "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
                    + "data: [DONE]\n\n"
                )
                data = payload.encode()
                writer.write(
                    (
                        "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                        f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n"
                    ).encode()
                    + data
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    agent = tmp_path / "agent"
    agent.mkdir()
    provider: dict[str, Any] = {
        "api": "openai-completions",
        "baseUrl": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1",
        "authHeader": True,
        "models": [
            {
                "id": "stub",
                "name": "Local stub",
                "reasoning": False,
                "input": ["text"],
                "contextWindow": 8192,
                "maxTokens": 64,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        ],
    }
    if credential == "config":
        provider["apiKey"] = SECRET
    (agent / "models.json").write_text(json.dumps({"providers": {"sdk-local": provider}}))
    (agent / "auth.json").write_text(
        json.dumps(
            {"sdk-local": {"type": "api_key", "key": SECRET}} if credential == "stored" else {}
        )
    )
    stdout: list[bytes] = []
    original = Transport._record

    def record(self: Transport, data: bytes, *, route: bool = True) -> None:
        stdout.append(data)
        original(self, data, route=route)

    monkeypatch.setattr(Transport, "_record", record)
    options: dict[str, Any] = {}
    if mode != "default":
        options["models"] = mode
    if directory == "explicit":
        options["pi_agent_dir"] = agent
    client = AsyncDurableClient(
        None,
        host_command=durable_host_command,
        inherit_env=False,
        env={
            "HOME": str(tmp_path),
            "PI_CODING_AGENT_DIR": str(agent if directory == "environment" else tmp_path / "other"),
            "PI_OFFLINE": "1",
            "AWS_EC2_METADATA_DISABLED": "true",
        },
        limits=Limits(stderr_tail_bytes=65536),
        settings={"retry": {"enabled": False}},
        **options,
    )
    async with server, client:
        cid = await client.root(model={"provider": "sdk-local", "modelId": "stub"})
        async with client.watch(cid) as subscription:
            await anext(subscription)
            sid = await client.submit(cid, "Synthetic question", request_id="configured-model")
            settled = await client.wait(sid, timeout=15)
            if mode == "builtin":
                assert settled.status == "unanswered" and settled.reason == "no_model"
                assert not calls
            else:
                assert settled.status == "done", settled.reason
                assert await client.answer_text(settled) == ANSWER
                assert len(calls) == 1
                assert calls[0]["request"] == "POST /v1/chat/completions HTTP/1.1"
                assert calls[0]["headers"]["authorization"] == f"Bearer {SECRET}"
    assert any(b'"durable_watch"' in line for line in stdout)
    assert SECRET.encode() not in b"".join(stdout)
    assert SECRET not in client.stderr_tail
    assert len(client.stderr_tail.encode()) < 65536


@pytest.mark.parametrize(
    "fields",
    [
        {"models": None},
        {"models": "invalid"},
        {"models": 1},
        {"piAgentDir": None},
        {"piAgentDir": 1},
    ],
)
async def test_bad_model_fields(durable_host_command: list[str], fields: dict[str, Any]) -> None:
    # A fake Python field injection reaches the real host's validation unchanged.
    client = AsyncDurableClient(None, host_command=durable_host_command, inherit_env=False, faux=[])
    client._open_fields.update(fields)
    with pytest.raises(PiCommandError) as error:
        await client.start()
    assert error.value.code == "bad_params"
    await client.aclose()


@pytest.mark.parametrize("mode", ["pi", "builtin"])
async def test_faux_bypasses_agent_files(
    durable_host_command: list[str], tmp_path: Path, mode: str
) -> None:
    (tmp_path / "auth.json").write_text("not valid auth JSON")
    (tmp_path / "models.json").write_text("not valid model JSON")
    options: dict[str, Any] = {"models": mode}
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        inherit_env=False,
        pi_agent_dir=tmp_path,
        faux=["Faux ignores agent files."],
        **options,
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await client.submit(cid, "Synthetic question", request_id="faux-override")
        settled = await client.wait(sid, timeout=10)
        assert settled.status == "done"
        assert await client.answer_text(settled) == "Faux ignores agent files."


async def test_eof_during_model_runtime_startup(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    process = await asyncio.create_subprocess_exec(
        *durable_host_command,
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PI_CODING_AGENT_DIR": str(tmp_path), "PI_OFFLINE": "1"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(15):
            stdout, _ = await process.communicate(
                json.dumps(
                    {"id": "opening", "type": "open", "storage": {"kind": "memory"}}
                ).encode()
                + b"\n"
            )
        assert process.returncode == 0
        assert not stdout  # The abandoned open must not publish a response.
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def test_constructor_signature_parity() -> None:
    assert inspect.signature(AsyncDurableClient) == inspect.signature(DurableClient)
    for cls in (AsyncDurableClient, DurableClient):
        client = cls(None, models="builtin", pi_agent_dir=Path("synthetic-agent"))
        asynchronous = client if isinstance(client, AsyncDurableClient) else client._client
        assert asynchronous._open_fields["models"] == "builtin"
        assert asynchronous._open_fields["piAgentDir"] == "synthetic-agent"
