"""CLI construction and offline compatibility checks for the owned process."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from ._transport import _close_process_pipes, _wait_for_exit
from .errors import PiProcessError, PiVersionError

MINIMUM_PI_VERSION = "0.85.1"
TESTED_PI_VERSION = "0.87.0"

# The client owns these options. In particular --print consumes an initial prompt.
_RESERVED = {
    "--mode",
    "--print",
    "-p",
    "--help",
    "-h",
    "--version",
    "-v",
    "--export",
    "--list-models",
    "--resume",
    "-r",
    "--continue",
    "-c",
    "--session",
    "--session-dir",
    "--session-id",
    "--fork",
    "--no-session",
    "--provider",
    "--model",
}
_VALUES = {
    "--api-key",
    "--system-prompt",
    "--append-system-prompt",
    "--name",
    "-n",
    "--models",
    "--tools",
    "-t",
    "--exclude-tools",
    "-xt",
    "--thinking",
    "--extension",
    "-e",
    "--skill",
    "--prompt-template",
    "--theme",
    "--use-theme",
    "--tui-mode",
}
_FLAGS = {
    "--no-tools",
    "-nt",
    "--no-builtin-tools",
    "-nbt",
    "--no-extensions",
    "-ne",
    "--no-skills",
    "-ns",
    "--no-prompt-templates",
    "-np",
    "--no-themes",
    "--no-context-files",
    "-nc",
    "--verbose",
    "--approve",
    "-a",
    "--no-approve",
    "-na",
    "--offline",
}


def validate_extra_args(args: Sequence[str]) -> None:
    """Reject positional input and conflicting flags, retaining extension flags."""
    index = 0
    while index < len(args):
        arg = args[index]
        name = arg.split("=", 1)[0]
        if name in _RESERVED or arg == "--":
            raise ValueError(f"Pi option {name} is managed by the client or incompatible with RPC")
        if name in _VALUES:
            if "=" in arg or index + 1 == len(args):
                raise ValueError(f"Pi option {name} requires a separate value")
            if name in {"--use-theme", "--tui-mode"} and args[index + 1].startswith("-"):
                raise ValueError(f"Pi option {name} requires a value before another option")
            index += 2
        elif name in _FLAGS:
            if "=" in arg:
                raise ValueError(f"Pi option {name} takes no value")
            index += 1
        elif arg.startswith("--"):
            # Pi accepts extension flags as --name=value or --name [value].
            index += 1
            if "=" not in arg and index < len(args) and not args[index].startswith(("-", "@")):
                index += 1
        else:
            raise ValueError(
                "extra_args cannot contain startup prompts, attachments, or unknown short flags"
            )


def executable_argv(
    executable: str | os.PathLike[str] | Sequence[str], env: Mapping[str, str]
) -> list[str]:
    """Resolve a binary or explicit argv; npm's Windows shim runs through Node."""
    if isinstance(executable, (str, os.PathLike)):
        argv = [os.fspath(executable)]
    else:
        argv = list(executable)
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("executable must be a path or a nonempty sequence of arguments")
    resolved = shutil.which(argv[0], path=env.get("PATH"))
    if resolved is None:
        raise PiProcessError("Pi executable was not found; install Pi or specify executable")
    if os.name == "nt" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        # Avoid shell=True and cmd quoting. Only the known npm Pi shim layout is resolved.
        root = Path(resolved).parent
        cli = root / "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
        node = root / "node.exe"
        node_path = str(node) if node.is_file() else shutil.which("node", path=env.get("PATH"))
        if not cli.is_file() or node_path is None:
            raise PiProcessError(
                "Cannot resolve Pi npm shim; pass executable=[node_path, pi_cli_path]"
            )
        return [node_path, str(cli), *argv[1:]]
    return [resolved, *argv[1:]]


async def check_version(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str],
    timeout: float,
    allow_unknown: bool,
    strict: bool,
) -> tuple[str | None, str]:
    """Read --version without a network request or loading user configuration."""
    process: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(timeout):
            process = await asyncio.create_subprocess_exec(
                *argv,
                "--version",
                cwd=cwd,
                env=dict(env),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert process.stdout is not None
            output = bytearray()
            while chunk := await process.stdout.read(4097 - len(output)):
                output.extend(chunk)
                if len(output) > 4096:
                    raise PiVersionError("Pi --version returned too much output")
            code = await process.wait()
            match = re.fullmatch(rb"\s*(\d+)\.(\d+)\.(\d+)\s*", output)
            if code != 0 or match is None:
                if allow_unknown:
                    return None, "unknown"
                raise PiVersionError(
                    "Cannot determine Pi version; custom wrappers may use "
                    "allow_unknown_version=True"
                )
            version = tuple(int(part) for part in match.groups())
            version_text = ".".join(str(part) for part in version)
            if version < tuple(map(int, MINIMUM_PI_VERSION.split("."))):
                raise PiVersionError(
                    f"Pi {version_text} is older than minimum {MINIMUM_PI_VERSION}"
                )
            if version_text != TESTED_PI_VERSION and strict:
                raise PiVersionError(
                    f"Pi {version_text} is untested; recorded tested version is {TESTED_PI_VERSION}"
                )
            return version_text, "tested" if version_text == TESTED_PI_VERSION else "untested"
    except TimeoutError as exc:
        raise PiVersionError("Timed out checking Pi version") from exc
    except OSError as exc:
        raise PiProcessError("Could not launch Pi for version checking") from exc
    finally:
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                # Process.wait() may depend on full or inherited pipes closing.
                # Wait for the owned child's exit first, then release those pipes.
                await _wait_for_exit(process)
            _close_process_pipes(process)
            await process.wait()
