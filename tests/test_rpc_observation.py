"""Public raw-byte and parsed-record observation, including failed teardown."""

import asyncio
import json
import sys

import pytest

from pi_agent import (
    AsyncPiClient,
    Limits,
    PiClient,
    PiCommandError,
    PiProcessError,
    PiProtocolError,
)

CHILD = """
import json, sys
if "--version" in sys.argv:
    print("0.85.1")
    sys.exit()
def emit(value):
    print(json.dumps(value), flush=True)
session_id="fixture"
def response(request, **fields):
    return {"type":"response", "id":request["id"], "command":request["type"], "success":True,
            "data":{"sessionId":session_id, "isStreaming":False, "isCompacting":False,
                    "pendingMessageCount":0}, **fields}
emit({"type":"startup", "future":{"values":[1]}})
for line in sys.stdin:
    request=json.loads(line)
    command=request["type"]
    if command == "new_session":
        session_id="second-session"
        emit(response(request, data={"cancelled":False}))
    elif command == "deep":
        value={"marker":"deep"}
        for _ in range(500):
            value={"nested":value}
        emit(response(request, data=value))
    elif command == "fail":
        emit(response(request, success=False, error="synthetic rejection"))
    elif command == "duplicate":
        reply=response(request)
        emit(reply)
        emit(reply)
        emit({"type":"response", "id":"late", "command":"prompt", "success":False, "error":"late"})
    elif command == "malformed":
        sys.stdout.buffer.write(b'\\xffnot json\\n\\n{"type":"after_bad","future":true}\\n')
        sys.stdout.buffer.flush()
    elif command == "invalid_envelope":
        emit({"future":"object without type"})
        emit({"type":"after_bad"})
    elif command == "oversize":
        emit({"type":"huge", "data":"x"*200000})
        emit({"type":"after_bad"})
    else:
        emit(response(request))
sys.stdout.buffer.write(b'{"type":"shutdown"}\\npartial\\xff')
sys.stdout.buffer.flush()
"""


@pytest.fixture
def options(tmp_path):
    script = tmp_path / "observed_pi.py"
    script.write_text(CHILD)
    return {"executable": [sys.executable, str(script)]}


def sources(records, source):
    return [r.data for r in records if r.source == source]


async def test_all_rpc_responses_and_mutation_isolation(options):
    pi = AsyncPiClient(**options)
    async with pi.observe(stdout=True, rpc=True) as first, pi.observe(rpc=True) as second:
        try:
            await pi.start()
            await pi.request("duplicate")
            with pytest.raises(PiCommandError):
                await pi.request("fail")
            await pi.prompt("one")
            await pi.new_session()
            assert (await pi.get_state())["sessionId"] == "second-session"
            await pi.prompt("two")
        finally:
            await pi.aclose()
        all_records = [r async for r in first]
        records = sources(all_records, "rpc")
        other = sources([r async for r in second], "rpc")
        assert records == other
        records[0]["future"]["values"].append("mutated")
        assert other[0]["future"]["values"] == [1]
        startup = next(r for r in other if r.get("command") == "get_state")
        startup["data"]["sessionId"] = "mutated"
        assert (
            next(r for r in records if r.get("command") == "get_state")["data"]["sessionId"]
            == "fixture"
        )
        assert sum(r.get("command") == "duplicate" for r in other) == 2
        assert sum(r.get("command") == "prompt" for r in other) == 3
        assert next(r for r in other if r.get("command") == "fail")["success"] is False
        assert other[-1] == {"type": "shutdown"}
        raw = b"".join(sources(all_records, "stdout"))
        assert raw.endswith(b'{"type":"shutdown"}\npartial\xff')
        parsed = [json.loads(line) for line in raw.splitlines()[:-1]]
        assert len(parsed) == len(other)  # no extra parsed delivery from cleanup
        assert first.status.complete and second.status.complete
        assert first.status.error is None
        assert any(r.get("data", {}).get("sessionId") == "second-session" for r in other)


@pytest.mark.parametrize("command", ["malformed", "invalid_envelope"])
async def test_protocol_error_preserved_while_shutdown_capture_continues(options, command):
    pi = AsyncPiClient(**options)
    async with pi.observe(stderr=False, stdout=True, rpc=True) as output:
        await pi.start()
        with pytest.raises(PiProtocolError) as failure:
            await pi.request(command)
        await pi.aclose()
        records = [r async for r in output]
        raw = b"".join(sources(records, "stdout"))
        assert raw.endswith(b'{"type":"shutdown"}\npartial\xff')
        if command == "malformed":
            assert b"\xffnot json\n\n" in raw
        else:
            assert {"future": "object without type"} in sources(records, "rpc")
        assert any(r.get("type") == "after_bad" for r in sources(records, "rpc"))
        assert output.status.error is failure.value
        assert output.status.complete
        assert output.status.stdout_eof
        assert not pi.running


async def test_observer_mutation_during_execution_cannot_change_routing(options):
    pi = AsyncPiClient(**options)
    async with pi.observe(stderr=False, rpc=True) as output:
        changed = asyncio.Event()

        async def consume():
            async for record in output:
                if record.data.get("command") == "get_state":
                    record.data["data"]["sessionId"] = "untrusted mutation"
                    record.data["success"] = False
                    changed.set()

        consumer = asyncio.create_task(consume())
        try:
            await pi.start()
            await asyncio.wait_for(changed.wait(), 2)
            assert pi.session.session_id == "fixture"
            assert (await pi.get_state())["sessionId"] == "fixture"
        finally:
            await pi.aclose()
            await consumer


def test_sync_raw_and_rpc_capture_after_protocol_failure(options):
    pi = PiClient(**options)
    with pi.observe(stdout=True, rpc=True) as output:
        pi.start()
        with pytest.raises(PiProtocolError) as failure:
            pi.request("malformed")
        pi.close()
        records = list(output)
        assert b"\xffnot json\n\n" in b"".join(sources(records, "stdout"))
        assert sources(records, "rpc")[-1] == {"type": "shutdown"}
        assert output.status.error is failure.value
        assert output.status.complete


@pytest.mark.parametrize("blocking", [False, True])
async def test_failed_spawn_and_prestart_close_are_incomplete(blocking):
    if blocking:

        def run():
            pi = PiClient(executable="missing-pi-executable")
            with pi.observe(stdout=True, rpc=True) as output:
                with pytest.raises(PiProcessError) as failure:
                    pi.start()
                assert list(output) == []
                assert output.status.error is failure.value
                assert output.status.ended_at_ns is not None
                assert not output.status.complete

        await asyncio.to_thread(run)
    else:
        pi = AsyncPiClient(executable="missing-pi-executable")
        async with pi.observe(stdout=True, rpc=True) as output:
            with pytest.raises(PiProcessError) as failure:
                await pi.start()
            assert [r async for r in output] == []
            assert output.status.error is failure.value
            assert output.status.ended_at_ns is not None
            assert not output.status.complete


async def test_oversized_objects_mark_rpc_incomplete_but_preserve_raw_bytes(options):
    pi = AsyncPiClient(**options, limits=Limits(max_record_bytes=512))
    async with pi.observe(stderr=False, stdout=True) as raw, pi.observe(rpc=True) as rpc:
        await pi.start()
        with pytest.raises(PiProtocolError):
            await pi.request("oversize")
        await pi.aclose()
        data = b"".join([r.data async for r in raw])
        assert b"x" * 200000 in data
        assert raw.status.complete
        assert not rpc.status.complete and not rpc.status.rpc_complete
        assert any([r.data.get("type") == "after_bad" async for r in rpc])


def test_blocking_consumer_can_drain_concurrently_with_client_close(options):
    from concurrent.futures import ThreadPoolExecutor

    pi = PiClient(**options)
    with pi.observe(stdout=True, rpc=True) as output, ThreadPoolExecutor(1) as workers:
        consumer = workers.submit(list, output)
        try:
            pi.start()
            pi.request("duplicate")
        finally:
            pi.close()
        records = consumer.result(timeout=2)
        assert sources(records, "rpc")[-1] == {"type": "shutdown"}
        assert output.status.complete


async def test_observer_selection_and_close_before_spawn():
    pi = AsyncPiClient(executable="does-not-exist")
    with pytest.raises(ValueError):
        pi.observe(stderr=False)
    async with pi.observe(stdout=True, rpc=True) as output:
        reader = asyncio.create_task(anext(output))
        await pi.aclose()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(reader, 1)
        assert not output.status.complete
        assert output.status.started_at_ns is None
        assert output.status.ended_at_ns is not None


async def test_deep_valid_response_is_not_broken_by_observation(options):
    pi = AsyncPiClient(**options)
    async with pi.observe(stderr=False, rpc=True) as output:
        try:
            await pi.start()
            response = await pi.request("deep")
            value = response["data"]
            for _ in range(500):
                value = value["nested"]
            assert value == {"marker": "deep"}
        finally:
            await pi.aclose()
        records = [r async for r in output]
        assert any(r.data.get("command") == "deep" for r in records)
        assert output.status.complete
