"""CLI validation must preserve Pi defaults without permitting startup input."""

import os
import sys

import pytest

from pi_coding_agent_client._launch import check_version, executable_argv, validate_extra_args
from pi_coding_agent_client.errors import PiVersionError


@pytest.mark.parametrize(
    "args",
    [
        ["hello"],
        ["@image.png"],
        ["--", "hello"],
        ["--mode", "json"],
        ["--print", "hello"],
        ["--session=x"],
        ["--no-tools", "hello"],
        ["--extension"],
        ["--no-tools=true"],
    ],
)
def test_no_startup_input(args):
    with pytest.raises(ValueError):
        validate_extra_args(args)


def test_extension_options_and_explicit_defaults_are_allowed():
    validate_extra_args(
        ["--no-tools", "--extension", "fixture.ts", "--custom=value", "--another", "value"]
    )


def test_explicit_command_argv():
    assert executable_argv([sys.executable, "fixture.py"], os.environ)[1:] == ["fixture.py"]


@pytest.mark.parametrize(
    "version,strict,allow_unknown,expected",
    [
        ("0.85.1", False, False, ("0.85.1", "tested")),
        ("0.86.0", False, False, ("0.86.0", "untested")),
        ("custom", False, True, (None, "unknown")),
    ],
)
async def test_version_status(version, strict, allow_unknown, expected):
    result = await check_version(
        [sys.executable, "-c", f"print({version!r})"],
        cwd=None,
        env=os.environ,
        timeout=5,
        strict=strict,
        allow_unknown=allow_unknown,
    )
    assert result == expected


@pytest.mark.parametrize("version,strict", [("0.85.0", False), ("0.86.0", True), ("custom", False)])
async def test_unsupported_version(version, strict):
    with pytest.raises(PiVersionError):
        await check_version(
            [sys.executable, "-c", f"print({version!r})"],
            cwd=None,
            env=os.environ,
            timeout=5,
            strict=strict,
            allow_unknown=False,
        )
