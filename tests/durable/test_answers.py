"""Read-only answer helpers preserve opaque entry data and non-text content."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pi_agent.durable import AsyncDurableClient, SettledSubmission, entry_text


def test_answer_id_and_text_are_read_only() -> None:
    raw = {"status": "done", "answer": 42, "future": {"kept": True}}
    settled = SettledSubmission("done", None, raw)
    entry: dict[str, Any] = {
        "id": 42,
        "kind": "pi.assistant",
        "model": [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "not answer text"},
                    {"type": "text", "text": "First "},
                    {"type": "toolCall", "name": "ignored"},
                    {"type": "text", "text": "answer."},
                ],
            }
        ],
        "future": True,
    }
    before = copy.deepcopy(entry)
    assert settled.answer_id == 42
    assert entry_text(entry) == "First answer."
    assert entry == before
    assert settled.raw is raw and settled.raw["future"] == {"kept": True}


@pytest.mark.parametrize("answer", [None, True, "42", {}])
def test_unanswered_has_no_answer_id(answer: object) -> None:
    settled = SettledSubmission("unanswered", "no_model", {"answer": answer})
    assert settled.answer_id is None
    assert SettledSubmission("unanswered", "no_model", {}).answer_id is None


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {"model": None},
        {"model": [None]},
        {"model": [{"content": [{"type": "image", "data": "synthetic"}]}]},
        {"model": [{"content": [{"type": "text", "text": 123}]}]},
    ],
)
def test_entry_without_text(entry: dict[str, Any]) -> None:
    assert entry_text(entry) == ""


def test_string_content_and_multiple_model_messages() -> None:
    assert (
        entry_text(
            {
                "model": [
                    {"content": "first "},
                    {
                        "content": [
                            {"type": "text", "text": "second"},
                            {"type": "future", "text": "ignored"},
                        ]
                    },
                ]
            }
        )
        == "first second"
    )


@pytest.mark.parametrize("answered", [True, False])
async def test_real_answer_helper_flow(durable_host_command: list[str], answered: bool) -> None:
    async with AsyncDurableClient(
        None,
        host_command=durable_host_command,
        inherit_env=False,
        faux=["Synthetic answer"],
    ) as client:
        cid = await client.root(
            model={"provider": "faux", "modelId": "faux-1" if answered else "missing"}
        )
        sid = await client.submit(cid, "Synthetic question", request_id="answer-helper")
        settled = await client.wait(sid, timeout=10)
        entries = await client.entries(cid)
        if answered:
            assert settled.status == "done"
            assert settled.answer_id is not None
            answer = next(entry for entry in entries if entry["id"] == settled.answer_id)
            assert entry_text(answer) == "Synthetic answer"
        else:
            assert settled.status == "unanswered" and settled.reason == "no_model"
            assert settled.answer_id is None
