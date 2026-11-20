"""Opt-in launch arguments for unattended Pi runs.

Pi's defaults suit an interactive coding agent: it discovers extensions, skills,
prompt templates, themes, context files such as ``AGENTS.md``, MCP servers and
project-local resources from the working directory and agent directory. Batch
jobs, services and evaluations usually want the opposite: only what the caller
names. :func:`headless_args` builds that command line explicitly for
``extra_args``; nothing here changes the clients' defaults or reads Pi files.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import get_args

from .types import ThinkingLevel

__all__ = ["headless_args"]

# Discovery that headless_args always disables. Explicit --extension and --skill
# paths still load: Pi applies these switches to discovery, not to named paths.
_DISCOVERY_OFF = (
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
    "--no-approve",
)
_THINKING_LEVELS = frozenset(get_args(ThinkingLevel))


def headless_args(
    *,
    tools: Sequence[str] = (),
    extensions: Sequence[str | os.PathLike[str]] = (),
    skills: Sequence[str | os.PathLike[str]] = (),
    system_prompt: str | None = None,
    append_system_prompt: Sequence[str] = (),
    thinking: ThinkingLevel | None = None,
    mcp: bool = False,
    offline: bool = True,
    prompt_files: bool = False,
) -> list[str]:
    """Return ``extra_args`` that load only what the caller names.

    Always disables discovery of extensions, skills, prompt templates, themes,
    context files (``AGENTS.md``/``CLAUDE.md``) and project-local resources.
    Named ``extensions`` and ``skills`` still load; filesystem paths are resolved
    against the Python process's current directory because Pi may run in a
    different ``cwd``. ``builtin:<name>`` extensions pass through unchanged.

    ``tools`` is an allowlist passed to ``--tools`` in order, without duplicates.
    With no tools, every tool is disabled; when extensions are named, only
    built-in tools are disabled so extension tools remain available.

    ``system_prompt`` replaces Pi's built-in system prompt; ``None`` or ``""``
    keeps the built-in prompt. Each ``append_system_prompt`` entry adds one
    ``--append-system-prompt``. Pi reads a prompt value that names an existing
    file as that file's contents.

    ``prompt_files=False`` stops Pi from loading ``SYSTEM.md`` (which replaces
    the built-in prompt) and ``APPEND_SYSTEM.md`` (which extends it) from its
    agent directory, so a file added for interactive use cannot change
    unattended runs. Set it to true to load them; an explicit ``system_prompt``
    or ``append_system_prompt`` still takes precedence over the matching file.
    Project ``.pi/`` copies stay ignored because project-local files are not
    trusted.
    ``mcp=False`` passes ``--no-mcp``. Pi 1.3.0 added built-in MCP and that
    option; older Pi exits on it at startup, so pass ``mcp=True`` there.
    ``offline=True`` passes ``--offline`` and skips startup network operations
    such as Pi's model-catalog refresh.

    Pi still reads models, credentials and settings from its agent directory;
    choose it with ``env={"PI_CODING_AGENT_DIR": ...}`` for full isolation.

    Raises ValueError for a bare string where a sequence is expected, an empty
    tool name, a tool name containing a comma, an empty path, or an unknown
    thinking level.
    """
    for name, value in (
        ("tools", tools),
        ("extensions", extensions),
        ("skills", skills),
        ("append_system_prompt", append_system_prompt),
    ):
        # A bare string is a Sequence[str] and would silently split into characters.
        if isinstance(value, str):
            raise ValueError(f"{name} must be a sequence of strings, not a string")
    enabled: list[str] = []
    for tool in tools:
        if not isinstance(tool, str) or not tool.strip() or "," in tool:
            raise ValueError("tool names must be nonempty strings without commas")
        if tool not in enabled:
            enabled.append(tool)
    if thinking is not None and thinking not in _THINKING_LEVELS:
        raise ValueError(f"thinking must be one of {sorted(_THINKING_LEVELS)}")

    arguments = list(_DISCOVERY_OFF)
    if not mcp:
        arguments.append("--no-mcp")
    if offline:
        arguments.append("--offline")
    # Pi treats an empty prompt value as unset, keeping its built-in prompt, but
    # any supplied value skips SYSTEM.md / APPEND_SYSTEM.md discovery.
    if system_prompt is not None:
        arguments.extend(("--system-prompt", system_prompt))
    elif not prompt_files:
        arguments.extend(("--system-prompt", ""))
    for text in append_system_prompt:
        arguments.extend(("--append-system-prompt", text))
    if not append_system_prompt and not prompt_files:
        arguments.extend(("--append-system-prompt", ""))
    if thinking is not None:
        arguments.extend(("--thinking", thinking))
    for extension in extensions:
        arguments.extend(("--extension", _resolve(extension, allow_builtin=True)))
    for skill in skills:
        arguments.extend(("--skill", _resolve(skill, allow_builtin=False)))
    if enabled:
        arguments.extend(("--tools", ",".join(enabled)))
    elif extensions:
        arguments.append("--no-builtin-tools")
    else:
        arguments.append("--no-tools")
    return arguments


def _resolve(path: str | os.PathLike[str], *, allow_builtin: bool) -> str:
    text = os.fspath(path)
    if not text:
        raise ValueError("extension and skill paths must be nonempty")
    if allow_builtin and isinstance(path, str) and text.startswith("builtin:"):
        return text
    return str(Path(text).resolve())
