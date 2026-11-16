"""Client answer-text convenience reads only, including history beyond 50 entries."""

from __future__ import annotations

import inspect
import sys
from typing import Literal

import pytest

from pi_agent import PiCommandError
from pi_agent.durable import AsyncDurableClient, DurableClient, SettledSubmission

# A protocol peer, not an engine: only hello/open/entries are implemented.
PEER = """
import json, os, sys
mode = sys.argv[1]
def entry(i, text):
    return dict(id=i, kind='pi.assistant',
                model=[dict(content=[dict(type='text', text=text)])])
for line in sys.stdin:
    request = json.loads(line)
    command = request['type']
    data = {}
    success = True
    if command == 'hello':
        data = dict(protocol=0, piDurable='1.5.2', pid=os.getpid())
    elif command == 'entries':
        if mode == 'unanswered':
            success = False  # Unanswered records must never issue a read.
        else:
            older = entry(1, 'old answer')
            newer = [entry(i, 'new answer') for i in range(2, 52)]
            if mode == 'nontext':
                older['model'] = [dict(content=[dict(type='image', data='synthetic')])]
                data = dict(entries=[older])
            elif mode == 'window':
                data = dict(entries=([older] + newer)[-request.get('limit', 50):])
            elif mode == 'missing':
                data = dict(entries=newer[-request.get('limit', 50):])
            elif mode == 'too_large':
                success = False
            else:
                data = dict(entries=[older])
    elif command != 'open':
        success = False
    response = dict(type='response', id=request['id'], command=command, success=success)
    if success:
        response['data'] = data
    else:
        response.update(error='synthetic read failure', code='too_large')
    print(json.dumps(response), flush=True)
"""


def command(mode: str) -> list[str]:
    return [sys.executable, "-u", "-c", PEER, mode]


def settlement(answered: bool = True) -> SettledSubmission:
    status: Literal["done", "unanswered"] = "done" if answered else "unanswered"
    return SettledSubmission(
        status,
        None if answered else "no_model",
        {"status": status, "conversationId": 1, "answer": 1 if answered else None},
    )


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("answered", "old answer"),
        ("unanswered", None),
        ("window", "old answer"),
        ("missing", None),
        ("nontext", ""),
    ],
)
async def test_async_answer_text(mode: str, expected: str | None) -> None:
    async with AsyncDurableClient(None, host_command=command(mode)) as client:
        if mode == "window":
            assert all(entry["id"] != 1 for entry in await client.entries(1))
        assert await client.answer_text(settlement(mode != "unanswered")) == expected


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("answered", "old answer"),
        ("unanswered", None),
        ("window", "old answer"),
    ],
)
def test_sync_answer_text(mode: str, expected: str | None) -> None:
    with DurableClient(None, host_command=command(mode)) as client:
        assert client.answer_text(settlement(mode != "unanswered")) == expected


async def test_read_size_failure_is_not_silently_treated_as_no_answer() -> None:
    async with AsyncDurableClient(None, host_command=command("too_large")) as client:
        with pytest.raises(PiCommandError) as caught:
            await client.answer_text(settlement())
        assert caught.value.code == "too_large"


def test_answer_text_signatures_match() -> None:
    assert inspect.signature(AsyncDurableClient.answer_text) == inspect.signature(
        DurableClient.answer_text
    )


async def test_real_answer_older_than_default_entries_window(
    durable_host_command: list[str],
) -> None:
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        inherit_env=False,
        faux=["first answer", *(["later answer"] * 30)],
    ) as client:
        cid = await client.root(model={"provider": "faux", "modelId": "faux-1"})
        sid = await client.submit(cid, "first", request_id="first")
        first = await client.wait(sid, timeout=10)
        for index in range(30):
            sid = await client.submit(cid, "later", request_id=f"later-{index}")
            await client.wait(sid, timeout=10)
        assert first.answer_id not in [entry["id"] for entry in await client.entries(cid)]
        assert await client.answer_text(first) == "first answer"
