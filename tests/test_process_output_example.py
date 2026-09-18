"""The runnable example keeps operation and sink failures distinguishable."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pi_agent import AsyncPiClient, PiProtocolError


@pytest.mark.parametrize("startup_fails", [False, True])
async def test_output_example_preserves_primary_failure(tmp_path, monkeypatch, startup_fails):
    example_path = Path(__file__).parents[1] / "examples/process_output.py"
    spec = importlib.util.spec_from_file_location("output_example", example_path)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    script = tmp_path / "pi.py"
    script.write_text("""
import json, sys
if "--version" in sys.argv:
    print("0.85.1")
    sys.exit()
sys.stderr.buffer.write(b"synthetic startup diagnostic")
sys.stderr.buffer.flush()
for line in sys.stdin:
    request = json.loads(line)
    if "--fail" in sys.argv:
        print("{", flush=True)
    else:
        print(json.dumps({"type": "response", "command": request["type"],
            "id": request["id"], "success": True, "data": {"sessionId": "fixture",
            "isStreaming": False, "isCompacting": False, "pendingMessageCount": 0}}), flush=True)
""")
    sink_failure = OSError("synthetic sink failure")

    class FailingSink:
        def write(self, data):
            raise sink_failure

    client = AsyncPiClient(
        executable=[sys.executable, str(script), *(["--fail"] if startup_fails else [])]
    )
    monkeypatch.setattr(example, "AsyncPiClient", lambda: client)
    monkeypatch.setattr(
        example, "sys", SimpleNamespace(stderr=SimpleNamespace(buffer=FailingSink()))
    )
    with pytest.raises(PiProtocolError if startup_fails else OSError) as caught:
        await asyncio.wait_for(example.main(), 3)
    if startup_fails:
        assert any("OSError: synthetic sink failure" in note for note in caught.value.__notes__)
    else:
        assert caught.value is sink_failure
    assert not client.running
