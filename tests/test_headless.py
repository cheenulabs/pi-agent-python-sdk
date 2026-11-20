"""Opt-in headless launch arguments and strict run results."""

from __future__ import annotations

from pathlib import Path

import pytest

import pi_agent
from pi_agent import PiIncompleteRunError, PiRunError, RunResult, SessionInfo, headless_args
from pi_agent._launch import validate_extra_args

DISCOVERY_OFF = [
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
    "--no-approve",
]


def test_default_disables_discovery_tools_mcp_and_startup_network() -> None:
    arguments = headless_args()
    assert arguments == [*DISCOVERY_OFF, "--no-mcp", "--offline", "--no-tools"]
    validate_extra_args(arguments)


def test_named_resources_load_in_caller_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    arguments = headless_args(
        tools=["read", "grep", "read", "mcp__docs__*"],
        extensions=["builtin:mcp", Path("ext.ts")],
        skills=["skills/review"],
        system_prompt="",
        append_system_prompt=["Answer in JSON.", "Be brief."],
        thinking="high",
        mcp=True,
        offline=False,
    )
    assert arguments == [
        *DISCOVERY_OFF,
        "--system-prompt",
        "",
        "--append-system-prompt",
        "Answer in JSON.",
        "--append-system-prompt",
        "Be brief.",
        "--thinking",
        "high",
        "--extension",
        "builtin:mcp",
        "--extension",
        str(tmp_path / "ext.ts"),
        "--skill",
        str(tmp_path / "skills/review"),
        "--tools",
        "read,grep,mcp__docs__*",
    ]
    validate_extra_args(arguments)


def test_extensions_without_tools_keep_only_extension_tools() -> None:
    arguments = headless_args(extensions=["builtin:example"])
    assert arguments[-1] == "--no-builtin-tools"
    assert "--no-tools" not in arguments


@pytest.mark.parametrize(
    "options",
    [
        {"tools": [""]},
        {"tools": ["read,write"]},
        {"tools": [" "]},
        {"thinking": "extreme"},
        {"skills": [""]},
        {"extensions": [""]},
    ],
)
def test_invalid_options_raise_before_launch(options: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        headless_args(**options)  # type: ignore[arg-type]


def test_headless_is_exported_without_changing_coding_namespace() -> None:
    assert pi_agent.headless_args is headless_args
    assert "headless_args" in pi_agent.__all__
    assert "PiIncompleteRunError" in pi_agent.__all__


def _result(text: str, stop_reason: str | None) -> RunResult:
    return RunResult(
        text=text,
        messages=[],
        stop_reason=stop_reason,
        session=SessionInfo(),
        elapsed_seconds=0.1,
    )


def test_complete_result_returns_itself() -> None:
    result = _result("answer", "stop")
    assert result.raise_for_incomplete() is result
    assert _result("", "stop").raise_for_incomplete(allow_empty=True).text == ""


@pytest.mark.parametrize(
    "text, stop_reason, reason",
    [
        ("partial private text", "length", "stop_reason"),
        ("", "toolUse", "stop_reason"),
        ("", "deferred", "stop_reason"),
        ("", None, "stop_reason"),
        (" \n", "stop", "empty_text"),
    ],
)
def test_incomplete_result_raises_with_partial_work(
    text: str, stop_reason: str | None, reason: str
) -> None:
    result = _result(text, stop_reason)
    with pytest.raises(PiIncompleteRunError) as caught:
        result.raise_for_incomplete()
    assert isinstance(caught.value, PiRunError)
    assert caught.value.result is result
    assert caught.value.reason == reason
    assert "private" not in str(caught.value)
