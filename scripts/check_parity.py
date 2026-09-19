"""Compare commands and events against pinned TS using a shared synthetic subprocess.

Requires the locked tests/pi installation. No provider or network calls are made.
Intentional error, deadline and lifecycle differences have separate regression tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pi_agent import AsyncPiClient, PiClient

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/rpc_parity.json"


def verify_reference() -> None:
    baseline = json.loads((ROOT / "compatibility.json").read_text())
    runtime = ROOT / "tests/pi/node_modules/@earendil-works/pi-coding-agent"
    assert (
        json.loads((runtime / "package.json").read_text())["version"] == baseline["testedVersion"]
    )
    for filename in ("rpc-client", "jsonl"):
        mapping = json.loads((runtime / f"dist/modes/rpc/{filename}.js.map").read_text())
        source = mapping["sourcesContent"][0].encode()
        key = f"packages/coding-agent/src/modes/rpc/{filename}.ts"
        assert hashlib.sha256(source).hexdigest() == baseline["sourceSha256"][key], key


async def check_async(fixture: dict[str, Any], options: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for nullable in (False, True):
        async with AsyncPiClient(**options, extra_args=["--null-cycles"] if nullable else []) as pi:
            seen: list[Any] = []
            remove = pi.on_event(seen.append)
            for case in fixture["cases"]:
                if case.get("nullable", False) != nullable:
                    continue
                seen.clear()
                result = await getattr(pi, case["py"])(*case["args"], **case["kwargs"])
                results.append(
                    {
                        "method": case["py"],
                        "commands": [e.raw["request"] for e in seen],
                        "result": result,
                    }
                )
            remove()
            if not nullable:
                first: list[Any] = []
                second: list[Any] = []
                off_first, off_second = pi.on_event(first.append), pi.on_event(second.append)
                events = await pi.prompt_and_wait("emit-corpus", timeout=5)
                off_first()
                off_second()
                for records in (events, first, second):
                    assert [e.raw for e in records] == fixture["events"]
    return results


def check_sync(fixture: dict[str, Any], options: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for nullable in (False, True):
        with PiClient(**options, extra_args=["--null-cycles"] if nullable else []) as pi:
            seen: list[Any] = []
            remove = pi.on_event(seen.append)
            for case in fixture["cases"]:
                if case.get("nullable", False) != nullable:
                    continue
                seen.clear()
                result = getattr(pi, case["py"])(*case["args"], **case["kwargs"])
                results.append(
                    {
                        "method": case["py"],
                        "commands": [e.raw["request"] for e in seen],
                        "result": result,
                    }
                )
            remove()
            if not nullable:
                first: list[Any] = []
                second: list[Any] = []
                off_first, off_second = pi.on_event(first.append), pi.on_event(second.append)
                events = pi.prompt_and_wait("emit-corpus", timeout=5)
                off_first()
                off_second()
                for records in (events, first, second):
                    assert [e.raw for e in records] == fixture["events"]
    return results


def main() -> None:
    verify_reference()
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Install Node and run npm ci --prefix tests/pi --ignore-scripts")
    fixture = json.loads(FIXTURE.read_text())
    assert len({case["py"] for case in fixture["cases"]}) == 33
    env = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
        if key in os.environ
    }
    with tempfile.TemporaryDirectory(prefix="pi-parity-") as directory:
        reference = json.loads(
            subprocess.check_output(
                [node, str(ROOT / "tests/pi/check-parity.mjs"), directory],
                cwd=directory,
                env=env,
                timeout=30,
            )
        )
        options = {
            "executable": [node, str(ROOT / "tests/pi/parity-child.cjs")],
            "cwd": directory,
            "inherit_env": False,
            "env": env,
        }
        asynchronous = asyncio.run(check_async(fixture, options))
        blocking = check_sync(fixture, options)
        for case, ts, py_async, py_sync in zip(
            fixture["cases"], reference, asynchronous, blocking, strict=True
        ):
            assert ts == py_async == py_sync, f"Command parity mismatch: {case['py']}"
    print(
        f"PASS: 33 commands / {len(reference)} cases and {len(fixture['events'])} events "
        "match TS, async Python, and blocking Python"
    )


if __name__ == "__main__":
    main()
