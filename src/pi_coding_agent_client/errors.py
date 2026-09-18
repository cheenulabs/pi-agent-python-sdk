"""Failures reported by the client; no exception automatically dumps wire payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import RunResult


class PiError(Exception):
    """Base class for client and Pi protocol failures."""


class PiCommandError(PiError):
    """Pi rejected a command. The original error is available explicitly."""

    def __init__(self, command: str, error: str, request_id: str | None = None) -> None:
        self.command = command
        self.error = error
        self.request_id = request_id
        # Extension errors can contain prompt text or provider diagnostics.
        super().__init__(f"Pi rejected command {command!r}; inspect .error for details")


class PiProtocolError(PiError):
    """The child emitted invalid framing or a malformed protocol envelope."""


class PiProcessError(PiError):
    """The owned process could not start or closed unexpectedly."""

    def __init__(self, message: str, returncode: int | None = None) -> None:
        self.returncode = returncode
        super().__init__(message)


class PiTimeoutError(PiError, TimeoutError):
    """A deadline elapsed; an uncertain operation may still have taken effect."""

    def __init__(
        self,
        message: str,
        command: str | None = None,
        request_id: str | None = None,
        uncertain: bool = True,
    ) -> None:
        self.command = command
        self.request_id = request_id
        self.uncertain = uncertain
        super().__init__(message)


class PiRunStartTimeout(PiTimeoutError):
    """An accepted prompt did not produce an observed run before its deadline."""


class PiBusyError(PiError):
    """The operation conflicts with an active owned run or stream consumer."""


class PiSubscriptionOverflow(PiError):
    """A subscriber exceeded its configured event buffer."""


class PiResultOverflow(PiError):
    """An owned run exceeded its independent retained-result capacity."""


class PiRunOwnershipError(PiBusyError):
    """Prior low-level work prevents reliable attribution of a new owned run."""


class PiUIHandlerError(PiError):
    """An extension UI callback failed."""


class PiRunError(PiError):
    """A settled run ended in error or abortion; .result preserves partial work."""

    def __init__(self, message: str, result: RunResult) -> None:
        self.result = result
        super().__init__(message)


class PiVersionError(PiError):
    """The selected Pi version does not meet the requested compatibility policy."""
