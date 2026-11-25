"""Drive the real Node host's JSONL protocol, without a Python Durable client."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from pi_agent.durable import TESTED_PI_DURABLE_VERSION

pytestmark = pytest.mark.integration


class Host:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.lines: list[bytes] = []
        self.events: list[dict[str, Any]] = []
        self.sequence = 0

    async def send(self, record: Any) -> None:
        await self.raw(json.dumps(record, ensure_ascii=False).encode() + b"\n")

    async def raw(self, line: bytes) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(line)
        await self.process.stdin.drain()

    async def record(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        async with asyncio.timeout(30):
            line = await self.process.stdout.readline()
        assert line, f"Host exited: {self.process.returncode}"
        self.lines.append(line.rstrip(b"\n"))
        result: dict[str, Any] = json.loads(line)
        assert isinstance(result, dict)
        return result

    async def response(self, request: dict[str, Any]) -> dict[str, Any]:
        while True:
            result = await self.record()
            if result["type"] != "response":
                self.events.append(result)
                continue
            assert result["id"] == request["id"]
            assert result["command"] == request["type"]
            assert isinstance(result["success"], bool)
            if result["success"]:
                assert isinstance(result["data"], dict)
            else:
                assert isinstance(result["error"], str)
                assert isinstance(result["code"], str)
            return result

    async def request(self, command: str, **fields: Any) -> dict[str, Any]:
        self.sequence += 1
        request = {"id": f"req-雪-{self.sequence}", "type": command, **fields}
        await self.send(request)
        return await self.response(request)

    async def ok(self, command: str, **fields: Any) -> dict[str, Any]:
        result = await self.request(command, **fields)
        assert result["success"], result
        return result["data"]  # type: ignore[no-any-return]

    async def error(self, command: str, code: str, **fields: Any) -> dict[str, Any]:
        result = await self.request(command, **fields)
        assert result["success"] is False
        assert result["code"] == code, result
        return result

    async def eof(self) -> tuple[int, list[dict[str, Any]]]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.close()
        async with asyncio.timeout(30):
            rest = await self.process.stdout.read()
            code = await self.process.wait()
        lines = rest.splitlines()
        self.lines.extend(lines)
        return code, [json.loads(line) for line in lines]


@asynccontextmanager
async def running_host(command: list[str], tmp_path: Path):
    # No provider keys or real user configuration reach the child.
    env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR") if key in os.environ}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), TMPDIR=str(tmp_path))
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=tmp_path,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=32 * 1024 * 1024,
    )
    try:
        yield Host(process)
    finally:
        if process.returncode is None:
            assert process.stdin is not None
            process.stdin.close()
            try:
                async with asyncio.timeout(5):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()


def storage(kind: str, tmp_path: Path) -> dict[str, str]:
    return (
        {"kind": "memory"}
        if kind == "memory"
        else {"kind": "sqlite", "path": str(tmp_path / "state.db")}
    )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
async def test_core_flow(durable_host_command: list[str], tmp_path: Path, kind: str) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        hello = await host.ok("hello")
        assert hello == {
            "protocol": 0,
            "piDurable": TESTED_PI_DURABLE_VERSION,
            "pid": host.process.pid,
        }
        assert (
            await host.ok("open", storage=storage(kind, tmp_path), faux=["Synthetic 雪 answer"])
            == {}
        )
        cid = (
            await host.ok(
                "root",
                agent={
                    "model": {"provider": "faux", "modelId": "faux-1"},
                    "cwd": str(tmp_path),
                    "thinkingLevel": "off",
                },
            )
        )["conversationId"]
        assert isinstance(cid, int)
        assert await host.ok(
            "root", agent={"model": {"provider": "ignored", "modelId": "ignored"}}
        ) == {"conversationId": cid}
        sid = (
            await host.ok(
                "submit",
                conversationId=cid,
                content="Synthetic question",
                requestId="job-1",
                whenBusy="followUp",
            )
        )["submissionId"]
        assert isinstance(sid, int)
        submission = (await host.ok("wait", submissionId=sid))["submission"]
        assert submission["id"] == sid
        assert submission["conversationId"] == cid
        assert submission["requestId"] == "job-1"
        assert submission["type"] == "input"
        assert submission["status"] == "done"
        entries = (await host.ok("entries", conversationId=cid))["entries"]
        assert [e["id"] for e in entries] == sorted(e["id"] for e in entries)
        assert entries[0]["kind"] == "pi.user"
        assert entries[-1]["kind"] == "pi.assistant"
        assert "Synthetic 雪 answer" in json.dumps(entries, ensure_ascii=False)
        assert (await host.ok("entries", conversationId=cid, limit=1))["entries"] == entries[-1:]
        assert await host.ok(
            "submit", conversationId=cid, content="ignored", requestId="job-1"
        ) == {"submissionId": sid}
        assert await host.ok("abort", conversationId=cid) == {}
        assert await host.eof() == (0, [])


@pytest.mark.parametrize("use_faux", [True, False])
async def test_missing_model_unanswered(
    durable_host_command: list[str], tmp_path: Path, use_faux: bool
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        options = {"faux": []} if use_faux else {}
        await host.ok("open", storage={"kind": "memory"}, codingTools=False, **options)
        cid = (await host.ok("root"))["conversationId"]
        sid = (
            await host.ok("submit", conversationId=cid, content="question", requestId="no-model")
        )["submissionId"]
        settled = (await host.ok("wait", submissionId=sid))["submission"]
        assert settled["status"] == "unanswered"
        assert isinstance(settled["reason"], str)


@pytest.mark.parametrize("coding_tools", [True, False])
async def test_faux_tools(
    durable_host_command: list[str], tmp_path: Path, coding_tools: bool
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        project = tmp_path / "agent-project"
        project.mkdir()
        await host.ok(
            "open",
            storage={"kind": "memory"},
            codingTools=coding_tools,
            faux=[
                {"tool": "write", "args": {"path": "synthetic.txt", "content": "fixture"}},
                "done",
            ],
        )
        cid = (
            await host.ok(
                "root",
                agent={"model": {"provider": "faux", "modelId": "faux-1"}, "cwd": str(project)},
            )
        )["conversationId"]
        sid = (
            await host.ok("submit", conversationId=cid, content="synthetic write", requestId="tool")
        )["submissionId"]
        assert (await host.ok("wait", submissionId=sid))["submission"]["status"] == "done"
        assert (project / "synthetic.txt").is_file() is coding_tools
        if coding_tools:
            assert (project / "synthetic.txt").read_text() == "fixture"


async def test_sqlite_reopen(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok("open", storage=storage("sqlite", tmp_path), faux=["saved"])
        cid = (await host.ok("root", agent={"model": {"provider": "faux", "modelId": "faux-1"}}))[
            "conversationId"
        ]
        sid = (await host.ok("submit", conversationId=cid, content="synthetic", requestId="saved"))[
            "submissionId"
        ]
        settled = await host.ok("wait", submissionId=sid)
        entries = await host.ok("entries", conversationId=cid)
        assert await host.eof() == (0, [])
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok("open", storage=storage("sqlite", tmp_path), faux=[])
        assert await host.ok("root") == {"conversationId": cid}
        assert await host.ok("wait", submissionId=sid) == settled
        assert await host.ok("entries", conversationId=cid) == entries


async def test_protocol_events(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.raw(b"{\n")
        assert await host.record() == {
            "type": "durable_protocol_error",
            "code": "parse_error",
            "message": "Invalid JSON",
        }
        for record in [
            None,
            [],
            {},
            {"id": 1, "type": "hello"},
            {"id": "x", "type": 1},
            {"id": "x"},
            {"type": "hello"},
        ]:
            await host.send(record)
            event = await host.record()
            assert event["type"] == "durable_protocol_error"
            assert event["code"] == "bad_request"
            assert isinstance(event["message"], str)
        # Any accidental extra response fails the next correlation assertion.
        await host.ok("hello")
        assert await host.eof() == (0, [])


async def test_lifecycle(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        for command in ["root", "submit", "wait", "entries", "abort", "unknown"]:
            await host.error(command, "not_open")
        await host.error(
            "open", "upstream_error", storage={"kind": "sqlite", "path": str(tmp_path)}, faux=[]
        )
        await host.error("root", "not_open")
        # Pipeline requests to exercise the opening gate, not just the open gate.
        first = {"id": "opening", "type": "open", "storage": {"kind": "memory"}, "faux": []}
        await host.raw(
            (
                json.dumps(first)
                + '\n{"id":"second","type":"open"}\n{"id":"early","type":"root"}\n'
            ).encode()
        )
        responses = [await host.record() for _ in range(3)]
        by_id = {r["id"]: r for r in responses}
        assert by_id["opening"]["data"] == {}
        assert by_id["second"]["code"] == "already_open"
        assert by_id["early"]["code"] == "not_open"
        await host.error("open", "already_open")
        await host.error("unknown", "unknown_command")
        # Watch commands now exist (M6), but still validate their required fields.
        await host.error("watch", "bad_params")
        await host.error("unwatch", "bad_params")
        assert await host.eof() == (0, [])


@pytest.mark.parametrize(
    "command,fields",
    [
        ("open", {}),
        ("open", {"storage": None}),
        ("open", {"storage": {"kind": "other"}}),
        ("open", {"storage": {"kind": "sqlite", "path": 1}}),
        *[
            ("open", {"storage": {"kind": "memory"}, **extra})
            for extra in [
                {"codingTools": "yes"},
                {"settings": []},
                {"settings": {"retry": []}},
                {"settings": {"retry": {"enabled": 1}}},
                {"settings": {"retry": {"maxRetries": 1.5}}},
                {"settings": {"progress": {"persistWithinMs": -1}}},
                {"maxRecordBytes": True},
                {"maxRecordBytes": 0},
                {"maxRecordBytes": 1.5},
                {"faux": "answer"},
                {"faux": [1]},
                {"faux": [{"tool": "read", "args": []}]},
                {"fauxTokensPerSecond": "fast"},
                {"fauxTokensPerSecond": 0},
            ]
        ],
        ("root", {"agent": []}),
        ("root", {"agent": {"model": {}}}),
        ("root", {"agent": {"cwd": False}}),
        ("root", {"agent": {"thinkingLevel": 2}}),
        ("submit", {}),
        ("submit", {"conversationId": True}),
        ("submit", {"conversationId": 0, "content": 2, "requestId": "key"}),
        ("submit", {"conversationId": 0, "content": "text", "requestId": ""}),
        (
            "submit",
            {"conversationId": 0, "content": "text", "requestId": "key", "whenBusy": "invalid"},
        ),
        ("wait", {}),
        ("wait", {"submissionId": "1"}),
        ("entries", {}),
        ("entries", {"conversationId": 0, "limit": -1}),
        ("entries", {"conversationId": 0, "limit": False}),
        ("abort", {}),
        ("abort", {"conversationId": 1.5}),
    ],
)
async def test_bad_params(
    durable_host_command: list[str], tmp_path: Path, command: str, fields: dict[str, Any]
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        if command != "open":
            await host.ok("open", storage={"kind": "memory"}, faux=[])
        await host.error(command, "bad_params", **fields)
        if command == "open":
            await host.error("root", "not_open")
            await host.ok("open", storage={"kind": "memory"}, faux=[])


@pytest.mark.parametrize(
    "command,fields",
    [
        ("submit", {"conversationId": 999999, "content": "x", "requestId": "key"}),
        ("entries", {"conversationId": 999999}),
        ("abort", {"conversationId": 999999}),
        ("wait", {"submissionId": 999999}),
    ],
)
async def test_not_found(
    durable_host_command: list[str], tmp_path: Path, command: str, fields: dict[str, Any]
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok("open", storage={"kind": "memory"}, faux=[])
        await host.error(command, "not_found", **fields)


async def test_busy_wait_concurrency_and_abort(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok(
            "open",
            storage={"kind": "memory"},
            faux=["Synthetic answer " * 1000],
            fauxTokensPerSecond=1,
            settings={"retry": {"baseDelayMs": 50}, "progress": {"persistWithinMs": 50}},
        )
        cid = (await host.ok("root", agent={"model": {"provider": "faux", "modelId": "faux-1"}}))[
            "conversationId"
        ]
        sid = (await host.ok("submit", conversationId=cid, content="q", requestId="slow"))[
            "submissionId"
        ]
        await host.error(
            "submit",
            "ConversationBusy",
            conversationId=cid,
            content="q2",
            requestId="reject",
            whenBusy="reject",
        )
        waiting = {"id": "pending-wait", "type": "wait", "submissionId": sid}
        await host.send(waiting)
        await host.ok("hello")  # wait cannot block requests on the same input stream
        await host.ok("entries", conversationId=cid)
        aborting = {"id": "abort", "type": "abort", "conversationId": cid}
        await host.send(aborting)
        results: dict[str, Any] = {}
        while len(results) < 2:
            result = await host.record()
            if result["type"] == "response":
                results[result["id"]] = result
        assert results["abort"]["data"] == {}
        assert results["pending-wait"]["data"]["submission"]["status"] == "unanswered"
        assert await host.ok("abort", conversationId=cid) == {}


async def test_eof_pending_wait(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok(
            "open", storage={"kind": "memory"}, faux=["slow " * 1000], fauxTokensPerSecond=1
        )
        cid = (await host.ok("root", agent={"model": {"provider": "faux", "modelId": "faux-1"}}))[
            "conversationId"
        ]
        sid = (await host.ok("submit", conversationId=cid, content="q", requestId="pending"))[
            "submissionId"
        ]
        await host.send({"id": "pending", "type": "wait", "submissionId": sid})
        await host.ok("hello")  # proves wait has been admitted before EOF
        assert await host.eof() == (0, [])


async def test_eof_during_open(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.send(
            {"id": "open", "type": "open", "storage": storage("sqlite", tmp_path), "faux": []}
        )
        code, records = await host.eof()
        assert code == 0
        assert all(r["type"] == "response" and r["id"] == "open" for r in records)


async def test_too_large(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.ok("open", storage={"kind": "memory"}, faux=["雪" * 1000], maxRecordBytes=512)
        cid = (await host.ok("root", agent={"model": {"provider": "faux", "modelId": "faux-1"}}))[
            "conversationId"
        ]
        sid = (await host.ok("submit", conversationId=cid, content="雪" * 1000, requestId="large"))[
            "submissionId"
        ]
        await host.ok("wait", submissionId=sid)
        await host.error("entries", "too_large", conversationId=cid)
        await host.ok("hello")
        assert all(len(line) <= 512 for line in host.lines)


async def test_failed_open_preserves_limit(durable_host_command: list[str], tmp_path: Path) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        await host.error(
            "open",
            "upstream_error",
            storage={"kind": "sqlite", "path": str(tmp_path)},
            faux=[],
            maxRecordBytes=1,
        )
        await host.ok("hello")
        await host.error("root", "not_open")
        assert await host.ok("open", storage={"kind": "memory"}, faux=[]) == {}
        await host.ok("hello")


async def test_oversized_diagnostic_is_dropped(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        opening = {
            "type": "open",
            "id": "",
            "storage": {"kind": "memory"},
            "faux": [],
            "maxRecordBytes": 78,
        }
        await host.send(opening)
        assert (await host.response(opening))["success"]
        # The parse_error event is 79 bytes: it must be dropped, not fatal.
        await host.raw(b"{\n")
        assert await host.eof() == (0, [])
        assert all(len(line) <= 78 for line in host.lines)


def fault_command(command: list[str], tmp_path: Path, script: str) -> list[str]:
    """Inject upstream faults in a Node preload, never in production host code."""
    upstream = Path(command[1]).parents[1] / "node_modules/@earendil-works/pi-durable/dist/index.js"
    preload = tmp_path / "upstream-fault.mjs"
    preload.write_text(
        f"import {{Harness, MemoryStorage}} from {json.dumps(upstream.as_uri())};\n" + script,
        encoding="utf-8",
    )
    return [command[0], "--unhandled-rejections=warn", "--import", str(preload), command[1]]


async def test_open_cleanup_preserves_original_error(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    command = fault_command(
        durable_host_command,
        tmp_path,
        """
Harness.open = async () => { throw new Error('synthetic open failure'); };
MemoryStorage.prototype.close = async () => { throw new Error('synthetic cleanup failure'); };
""",
    )
    async with running_host(command, tmp_path) as host:
        result = await host.error("open", "upstream_error", storage={"kind": "memory"}, faux=[])
        assert result["error"] == "synthetic open failure"
        await host.ok("hello")
        await host.error("root", "not_open")
        assert await host.eof() == (0, [])


async def test_reply_serialization_failure_exits_deliberately(
    durable_host_command: list[str], tmp_path: Path
) -> None:
    command = fault_command(
        durable_host_command,
        tmp_path,
        """
const open = Harness.open;
Harness.open = async (...args) => {
  const harness = await open(...args);
  harness.root = async () => ({id: 1n}); // Non-JSON upstream result.
  return harness;
};
""",
    )
    async with running_host(command, tmp_path) as host:
        await host.ok("open", storage={"kind": "memory"}, faux=[])
        await host.send({"id": "root", "type": "root"})
        # With Node's warn policy, an unhandled rejection alone cannot exit.
        # Keep stdin open to prove the reply path explicitly terminates.
        assert host.process.stdout is not None
        async with asyncio.timeout(30):
            assert await host.process.stdout.read() == b""
            assert await host.process.wait() != 0


@pytest.mark.parametrize("limit,long_id", [(1, False), (100, False), (256, True)])
async def test_unwritable_replacement(
    durable_host_command: list[str], tmp_path: Path, limit: int, long_id: bool
) -> None:
    async with running_host(durable_host_command, tmp_path) as host:
        opening = {
            "id": "x" * 1000 if long_id else "x",
            "type": "open",
            "storage": {"kind": "memory"},
            "faux": [],
            "maxRecordBytes": limit,
        }
        await host.send(opening)
        if limit == 100:
            # This open reply fits; wait for the new limit before sending hello.
            assert (await host.response(opening))["success"]
            await host.send({"id": "hello", "type": "hello"})
        assert host.process.stdout is not None
        async with asyncio.timeout(30):
            output = await host.process.stdout.read()
            code = await host.process.wait()
        assert code != 0
        assert all(len(line) <= limit for line in output.splitlines())
