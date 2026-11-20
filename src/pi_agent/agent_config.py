"""Temporary Pi agent configuration supplied from Python code.

Pi reads models, credentials, and settings from files in its agent directory
(``PI_CODING_AGENT_DIR``). :class:`AgentConfig` writes the caller's
configuration to a private temporary directory and returns the environment that
points a client at it, similar to the TypeScript SDK's ``agentDir`` option.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Self

__all__ = ["AgentConfig"]


def _mapping(value: object) -> dict[Any, Any]:
    # json encodes only dict; accept any Mapping (MappingProxyType, ChainMap, ...) at any depth.
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("not JSON serializable")


class AgentConfig:
    """Write ``models.json``, ``settings.json`` and ``auth.json`` for one use.

    Use as a context manager and pass ``config.env`` to the client's ``env=``::

        with AgentConfig(models=models, auth=auth) as config:
            with PiClient(env=config.env, no_session=True) as pi:
                ...

    Each mapping is written unchanged as the matching file; Pi owns the schemas.
    Omitted files are not written, so Pi uses its built-in defaults rather than
    the user's own agent directory. The directory is private and ``auth.json``
    is readable only by its owner where the platform supports it. On exit the
    directory and everything Pi wrote there, including default session files,
    are removed. Configuration values never appear in ``repr`` or errors.

    Raises ValueError when a value is not a mapping or cannot be encoded as
    JSON, and RuntimeError when the configuration is reused while active or
    read outside its context.
    """

    def __init__(
        self,
        *,
        models: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        auth: Mapping[str, Any] | None = None,
    ) -> None:
        self._files: dict[str, str] = {}
        for name, value in (("models", models), ("settings", settings), ("auth", auth)):
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
            try:
                text = json.dumps(dict(value), indent=2, allow_nan=False, default=_mapping)
            except (TypeError, ValueError):
                # The underlying message can quote configuration values.
                raise ValueError(f"{name} must contain only JSON-compatible values") from None
            self._files[f"{name}.json"] = text + "\n"
        self._directory: tempfile.TemporaryDirectory[str] | None = None

    def __repr__(self) -> str:
        state = "active" if self._directory is not None else "inactive"
        return f"<AgentConfig files={sorted(self._files)} {state}>"

    def __enter__(self) -> Self:
        if self._directory is not None:
            raise RuntimeError("AgentConfig is already active")
        # TemporaryDirectory creates the directory with mode 0700.
        directory = tempfile.TemporaryDirectory(prefix="pi-agent-config-")
        try:
            root = Path(directory.name)
            for name, text in self._files.items():
                mode = 0o600 if name == "auth.json" else 0o644
                descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
                with open(descriptor, "w", encoding="utf-8") as file:
                    file.write(text)
        except BaseException:
            directory.cleanup()
            raise
        self._directory = directory
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

    @property
    def path(self) -> Path:
        """The active agent directory."""
        if self._directory is None:
            raise RuntimeError("Use AgentConfig as a context manager: with AgentConfig(...) as c:")
        return Path(self._directory.name)

    @property
    def env(self) -> dict[str, str]:
        """Environment overrides for the clients' ``env=`` option."""
        return {"PI_CODING_AGENT_DIR": os.fspath(self.path)}
