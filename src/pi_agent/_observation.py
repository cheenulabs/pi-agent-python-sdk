"""Opt-in process output delivery; storage and forwarding belong to callers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ._events import _Subscription
from .errors import PiSubscriptionOverflow
from .types import Limits

OutputSource = Literal["stderr", "stdout", "rpc"]


@dataclass(frozen=True)
class ProcessOutput:
    """Original bytes or a parsed object from the RPC child, excluding the version probe."""

    source: OutputSource
    time_ns: int
    data: bytes | dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class ObservationStatus:
    """Delivery coverage, independent of RPC success and consumer storage."""

    started_at_ns: int | None = None
    ended_at_ns: int | None = None
    from_start: bool = False
    complete: bool = False
    lost: bool = False
    stderr_eof: bool = False
    stdout_eof: bool = False
    rpc_complete: bool = True
    error: Exception | None = field(default=None, repr=False)
    end_reason: Literal["stopped", "closed", "overflow", "process_end"] | None = None


class ProcessObservation(_Subscription[ProcessOutput]):
    """Bounded output iterator. Check status after draining to detect incomplete output."""

    def __init__(
        self,
        limits: Limits,
        register: Callable[[ProcessObservation], None],
        unregister: Callable[[ProcessObservation], None],
        sources: frozenset[OutputSource],
    ) -> None:
        super().__init__(limits, lambda: register(self), lambda: unregister(self))
        self._status = ObservationStatus()
        self._sources = sources

    @property
    def status(self) -> ObservationStatus:
        return self._status

    async def stop(self) -> None:
        """Unsubscribe without discarding queued output or closing the client.

        Drain the iterator afterwards, then inspect status. Repeated stops retain
        the first termination status, including overflow or process failure.
        """
        if not self._entered:
            raise RuntimeError("Enter the observation context before stopping")
        if not self._closed:
            self._status = replace(self._status, end_reason="stopped")
            self._finish()

    def _finish(self, error: Exception | None = None) -> None:
        if not self._closed and self._status.ended_at_ns is None:
            overflow = isinstance(error, PiSubscriptionOverflow)
            self._status = replace(
                self._status,
                ended_at_ns=time.time_ns(),
                lost=self._status.lost or overflow,
                error=error or self._status.error,
                end_reason="overflow" if overflow else self._status.end_reason or "closed",
            )
        super()._finish(error)

    def _discard(self, *, buffered: bool = False) -> None:
        if self._records or buffered:
            self._status = replace(
                self._status,
                complete=False,
                lost=True,
                end_reason="overflow" if self._status.end_reason == "overflow" else "closed",
            )
        super()._discard()
