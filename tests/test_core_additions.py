"""Additive core contracts shared by the coding and Durable backends."""

from __future__ import annotations

import sys
from typing import Any

import pytest

import pi_agent
from pi_agent import coding
from pi_agent._launch import child_env
from pi_agent._transport import Transport
from pi_agent.errors import PiCommandError
from pi_agent.types import Limits


def test_coding_namespace_identity() -> None:
    assert coding.PiClient is pi_agent.PiClient
    assert coding.AsyncPiClient is pi_agent.AsyncPiClient
    assert set(coding.__all__) == {"PiClient", "AsyncPiClient"}


@pytest.mark.parametrize("inherit", [True, False])
def test_child_environment(inherit: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_TEST_INHERITED", "inherited")
    monkeypatch.setenv("PI_TEST_OVERRIDE", "old")
    monkeypatch.setenv("PI_TEST_REMOVE", "remove")
    overrides = {"PI_TEST_OVERRIDE": "new", "PI_TEST_REMOVE": None, "PI_TEST_EMPTY": ""}
    environment = child_env(inherit, overrides)
    assert environment.get("PI_TEST_INHERITED") == ("inherited" if inherit else None)
    assert environment["PI_TEST_OVERRIDE"] == "new"
    assert environment["PI_TEST_EMPTY"] == ""
    assert "PI_TEST_REMOVE" not in environment
    assert child_env(True, {})["PI_TEST_REMOVE"] == "remove"
    if not inherit:
        assert environment == {"PI_TEST_OVERRIDE": "new", "PI_TEST_EMPTY": ""}
    assert overrides["PI_TEST_REMOVE"] is None


def test_command_error_positional_compatibility() -> None:
    error = PiCommandError("submit", "private", "request")
    assert error.code is None
    assert error.request_id == "request"
    assert PiCommandError("submit", "private", "request", "not_found").code == "not_found"
    assert "private" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields, expected",
    [
        ({}, None),
        ({"code": "not_found"}, "not_found"),
        ({"code": 42}, None),
        ({"code": None}, None),
        ({"code": ""}, ""),
    ],
)
async def test_command_error_code_passthrough(fields: dict[str, Any], expected: str | None) -> None:
    # A new peer rather than modifying any existing fixture or test.
    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line)\n"
        " print(json.dumps(dict(type='response',id=r['id'],command=r['type'],"
        "success=False,error='synthetic',**json.loads(sys.argv[1]))),flush=True)\n"
    )
    import json

    transport = Transport(limits=Limits(), on_event=lambda _: None, on_failure=lambda _: None)
    await transport.start([sys.executable, "-u", "-c", script, json.dumps(fields)])
    try:
        with pytest.raises(PiCommandError) as caught:
            await transport.request("submit")
        assert caught.value.code == expected
        assert caught.value.command == "submit"
        assert caught.value.request_id is not None
        assert caught.value.error == "synthetic"
        assert transport.running
    finally:
        await transport.aclose()
