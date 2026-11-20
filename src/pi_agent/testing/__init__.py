"""Test code that uses Pi without a model, credentials, or network access.

:class:`FakePi` provides a scripted stand-in executable. The real
:class:`~pi_agent.PiClient` and :class:`~pi_agent.AsyncPiClient` launch it as a
subprocess and speak the normal RPC protocol, so ``run()``, ``stream()``,
``RunResult`` and run errors behave as they do with Pi::

    from pi_agent.coding import PiClient
    from pi_agent.testing import FakePi, FakeReply

    with FakePi(["Hello!", FakeReply("cut off", stop_reason="length")]) as fake:
        with PiClient(executable=fake.executable) as pi:
            assert pi.run("Hi").text == "Hello!"
            assert pi.run("Again").stop_reason == "length"
        assert fake.prompts() == ["Hi", "Again"]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .._launch import TESTED_PI_VERSION

__all__ = ["FakePi", "FakeReply"]

_SCRIPT = Path(__file__).with_name("_fake_pi.py")


@dataclass(frozen=True)
class FakeReply:
    """One scripted assistant answer.

    ``stop_reason`` is reported as Pi's final stop reason: ``error`` and
    ``aborted`` make ``run()`` raise ``PiRunError``, and other values such as
    ``length`` are returned in ``RunResult.stop_reason``. ``usage`` overrides
    fields of Pi's wire usage record, for example ``{"input": 10, "output": 5}``.
    """

    text: str = ""
    stop_reason: str = "stop"
    thinking: str | None = None
    error_message: str | None = None
    usage: Mapping[str, Any] | None = None


class FakePi:
    """A scripted fake Pi executable for tests; use it as a context manager.

    Each prompt consumes the next reply; a prompt after the last reply is
    rejected with ``PiCommandError``. ``get_state`` and the commands the client
    sends automatically are supported, together with ``get_messages`` and
    ``get_last_assistant_text``. Other commands raise ``PiCommandError`` naming
    the unsupported command. Every client launched from the same ``FakePi``
    starts again from the first reply; ``requests()`` covers all of them.
    """

    def __init__(
        self,
        replies: Iterable[str | FakeReply] = (),
        *,
        version: str = TESTED_PI_VERSION,
        session_id: str = "fake-session",
        provider: str = "fake",
        model: str = "fake-model",
    ) -> None:
        self._script = {
            "replies": [
                {
                    "text": reply.text,
                    "stop_reason": reply.stop_reason,
                    "thinking": reply.thinking,
                    "error_message": reply.error_message,
                    "usage": dict(reply.usage) if reply.usage is not None else None,
                }
                for reply in (FakeReply(r) if isinstance(r, str) else r for r in replies)
            ],
            "version": version,
            "session_id": session_id,
            "model": {"provider": provider, "id": model},
        }
        self._directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Self:
        if self._directory is not None:
            raise RuntimeError("FakePi is already active")
        self._directory = tempfile.TemporaryDirectory(prefix="pi-agent-fake-")
        self._paths()[0].write_text(json.dumps(self._script), encoding="utf-8")
        self._paths()[1].touch()
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
    def executable(self) -> list[str]:
        """Argument list for the clients' ``executable=`` option."""
        script, log = self._paths()
        # -I ignores PYTHON* variables and user site-packages; the script needs neither.
        return [sys.executable, "-I", os.fspath(_SCRIPT), os.fspath(script), os.fspath(log)]

    def requests(self) -> list[dict[str, Any]]:
        """Every RPC request received so far, as wire dictionaries, in order."""
        text = self._paths()[1].read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line]

    def prompts(self) -> list[str]:
        """The messages of prompt requests received so far, in order."""
        return [r.get("message", "") for r in self.requests() if r.get("type") == "prompt"]

    def _paths(self) -> tuple[Path, Path]:
        if self._directory is None:
            raise RuntimeError("Use FakePi as a context manager: with FakePi(...) as fake:")
        root = Path(self._directory.name)
        return root / "script.json", root / "requests.jsonl"
