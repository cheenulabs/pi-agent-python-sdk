"""CLI validation must preserve Pi defaults without permitting startup input."""

import os
import sys

import pytest

from pi_agent._launch import check_version, executable_argv, validate_extra_args
from pi_agent.errors import PiVersionError


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


@pytest.mark.parametrize(
    "args",
    [
        ["--use-theme", "--help"],
        ["--tui-mode", "--mode", "--custom", "json"],
    ],
)
def test_conditionally_consumed_values_cannot_hide_reserved_flags(args):
    with pytest.raises(ValueError):
        validate_extra_args(args)


async def test_flooding_version_command_closes_without_waiting_for_full_pipe():
    import asyncio

    async with asyncio.timeout(2):
        with pytest.raises(PiVersionError):
            await check_version(
                [sys.executable, "-c", "import os; os.write(1, b'x' * 2000000)"],
                cwd=None,
                env=os.environ,
                timeout=0.2,
                strict=False,
                allow_unknown=False,
            )


def test_explicit_command_argv():
    assert executable_argv([sys.executable, "fixture.py"], os.environ)[1:] == ["fixture.py"]


@pytest.mark.parametrize(
    "version,strict,allow_unknown,expected",
    [
        ("0.85.1", False, False, ("0.85.1", "untested")),
        ("0.86.0", False, False, ("0.86.0", "untested")),
        ("0.86.1", True, False, ("0.86.1", "tested")),
        ("0.87.0", False, False, ("0.87.0", "untested")),
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


@pytest.mark.parametrize(
    "version,strict",
    [("0.85.0", False), ("0.85.1", True), ("0.87.0", True), ("custom", False)],
)
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


def test_windows_npm_shim_resolves_without_a_shell(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pi_agent import _launch

    shim = tmp_path / "pi.cmd"
    shim.touch()
    cli = tmp_path / "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
    cli.parent.mkdir(parents=True)
    cli.touch()
    node = tmp_path / "node.exe"
    node.touch()
    monkeypatch.setattr(
        _launch, "os", SimpleNamespace(name="nt", PathLike=os.PathLike, fspath=os.fspath)
    )
    monkeypatch.setattr(_launch.shutil, "which", lambda name, **kwargs: str(shim))
    assert executable_argv("pi", {}) == [str(node), str(cli)]


def test_unrecognized_windows_shim_has_actionable_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pi_agent import _launch
    from pi_agent.errors import PiProcessError

    monkeypatch.setattr(
        _launch, "os", SimpleNamespace(name="nt", PathLike=os.PathLike, fspath=os.fspath)
    )
    monkeypatch.setattr(
        _launch.shutil, "which", lambda name, **kwargs: str(tmp_path / "custom.cmd")
    )
    with pytest.raises(PiProcessError, match="executable="):
        executable_argv("custom.cmd", {})
